"""CineFlix - Registro de gastos (Flask + PostgreSQL en Neon)."""
import hmac
import os
import time
from datetime import date, timedelta
from functools import wraps

from dotenv import load_dotenv

load_dotenv()  # Lee el archivo .env cuando trabajas en tu computadora.

import psycopg2
import psycopg2.extras
from flask import (Flask, flash, redirect, render_template, request,
                   session, url_for)
from flask_wtf import CSRFProtect

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave-solo-para-desarrollo")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Render define la variable RENDER; allí la cookie solo viaja por HTTPS.
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
)
CSRFProtect(app)

DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

CATEGORIAS = [
    "Renta del local",
    "Servicios (luz, agua, internet)",
    "Nómina",
    "Mantenimiento",
    "Licencias de películas",
    "Dulcería e insumos",
    "Publicidad",
    "Otros",
]


# ------------------------------------------------------------ BASE DE DATOS
def get_conn():
    """Abre una conexión con PostgreSQL (Neon)."""
    if not DATABASE_URL:
        raise RuntimeError("Falta la variable de entorno DATABASE_URL.")
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=15,
    )


def db(sql, params=(), fetch=None):
    """Ejecuta una instrucción SQL y confirma (commit) los cambios."""
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch == "all":
                    return cur.fetchall()
                if fetch == "one":
                    return cur.fetchone()
    finally:
        conn.close()


def init_db():
    """Crea la tabla si todavía no existe."""
    db("""
        CREATE TABLE IF NOT EXISTS gastos (
            id SERIAL PRIMARY KEY,
            concepto TEXT NOT NULL,
            categoria TEXT NOT NULL,
            monto NUMERIC(12, 2) NOT NULL,
            fecha DATE NOT NULL,
            notas TEXT
        )
    """)


init_db()


# ------------------------------------------------------------------- SESIÓN
def login_required(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not session.get("autenticado"):
            return redirect(url_for("login"))
        return vista(*args, **kwargs)
    return envoltura


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("autenticado"):
        return redirect(url_for("gastos"))

    error = None
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")
        correcto = bool(
            ADMIN_PASSWORD
            and hmac.compare_digest(usuario.encode(), ADMIN_USER.encode())
            and hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
        )
        if correcto:
            session.clear()
            session["autenticado"] = True
            return redirect(url_for("gastos"))
        time.sleep(1)  # frena los intentos de adivinar la contraseña
        error = "Usuario o contraseña incorrectos."

    return render_template("login.html", errores=[error] if error else [])


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------- GASTOS
@app.route("/", methods=["GET", "POST"])
@login_required
def gastos():
    errores = []
    form_data = {}

    if request.method == "POST":
        concepto = request.form.get("concepto", "").strip()
        categoria = request.form.get("categoria", "").strip()
        monto_txt = request.form.get("monto", "").strip().replace(",", "")
        fecha_txt = request.form.get("fecha", "").strip()
        notas = request.form.get("notas", "").strip()
        form_data = request.form

        monto = 0.0
        try:
            monto = round(float(monto_txt), 2)
        except ValueError:
            errores.append("El monto debe ser un número.")
        else:
            if not (0 < monto <= 1_000_000):
                errores.append("El monto debe ser mayor a 0 y menor a 1,000,000.")

        try:
            fecha = date.fromisoformat(fecha_txt)
        except ValueError:
            fecha = None
            errores.append("Selecciona una fecha válida.")

        if not concepto:
            errores.append("El concepto es obligatorio.")
        if categoria not in CATEGORIAS:
            errores.append("Selecciona una categoría válida.")

        if not errores:
            db("""
                INSERT INTO gastos (concepto, categoria, monto, fecha, notas)
                VALUES (%s, %s, %s, %s, %s)
            """, (concepto, categoria, monto, fecha, notas))
            flash("¡Gasto registrado correctamente!", "success")
            return redirect(url_for("gastos"))

    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    inicio_sig = (inicio_mes + timedelta(days=32)).replace(day=1)

    lista = db("SELECT * FROM gastos ORDER BY fecha DESC, id DESC", fetch="all")
    total = db("SELECT COALESCE(SUM(monto), 0) AS total FROM gastos",
               fetch="one")["total"]
    total_mes = db("""
        SELECT COALESCE(SUM(monto), 0) AS total FROM gastos
        WHERE fecha >= %s AND fecha < %s
    """, (inicio_mes, inicio_sig), fetch="one")["total"]
    resumen = db("""
        SELECT categoria, SUM(monto) AS total
        FROM gastos GROUP BY categoria ORDER BY total DESC
    """, fetch="all")

    return render_template(
        "gastos.html",
        gastos=lista,
        total=total,
        total_mes=total_mes,
        resumen=resumen,
        categorias=CATEGORIAS,
        errores=errores,
        form_data=form_data,
        hoy=hoy.isoformat(),
    )


@app.route("/eliminar/<int:gasto_id>", methods=["POST"])
@login_required
def eliminar_gasto(gasto_id):
    db("DELETE FROM gastos WHERE id = %s", (gasto_id,))
    flash("El gasto fue eliminado.", "info")
    return redirect(url_for("gastos"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
