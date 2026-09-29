"""Logical clock control (PRD 2.5)."""
from flask import Blueprint

from db import db, fmt_dt
from middleware import HIE_ADMIN, authenticate
from response import ok
from validate import body, req_dt

bp = Blueprint("clock", __name__)


@bp.route("/hie/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate((HIE_ADMIN,))
    payload = body()
    _raw, parsed = req_dt(payload, "to_iso8601")
    db.clock = parsed
    return ok({"current_utc": fmt_dt(db.clock)})
