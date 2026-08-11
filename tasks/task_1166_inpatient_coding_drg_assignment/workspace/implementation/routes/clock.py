"""Logical clock control (PRD §2.5)."""
from flask import Blueprint

from db import iso, set_clock, store
from middleware import require_roles
from response import ok_obj
from validators import body, req_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("CodingManager")
    b = body()
    to = req_dt(b, "to_iso8601")
    set_clock(to)
    return ok_obj({"current_utc": iso(store.clock)}, 200)
