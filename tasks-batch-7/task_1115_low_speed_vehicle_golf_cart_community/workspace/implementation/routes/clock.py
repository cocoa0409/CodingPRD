"""Logical clock endpoint (PlatformAdmin only, mounted outside /api)."""
from flask import Blueprint

import db
from errors import err_validation
from middleware import get_caller, require_role
from response import ok_object
from services import engine

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    caller = get_caller()
    require_role(caller, ["PlatformAdmin"])
    from services import validate as v
    data = v.body()
    to_dt = v.require_datetime(data, "to_iso8601")
    db.set_clock(to_dt)
    engine.evaluate_time_transitions()
    return ok_object({"current_utc": db.format_ts(db.now())})
