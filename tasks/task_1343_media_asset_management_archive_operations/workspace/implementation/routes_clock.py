"""Logical clock endpoint (SystemAdmin)."""
from flask import Blueprint

import cascades
from auth import require_roles
from db import fmt_dt, set_clock
from envelope import ok
from errors import raise_err
from validate import body, req_dt

bp = Blueprint("clock", __name__, url_prefix="/archive")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("SystemAdmin")
    j = body()
    dt = req_dt(j, "to_iso8601")
    set_clock(dt)
    cascades.clock_sweep()
    return ok({"current_utc": fmt_dt(dt)}, 200)
