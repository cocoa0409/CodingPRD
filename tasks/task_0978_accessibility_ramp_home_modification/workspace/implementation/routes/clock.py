"""Logical clock test-driving endpoint."""
from flask import Blueprint

from core import (
    ApiError, body, ok_object, require_roles, parse_dt,
)
from core import CLOCK
from domain import tick

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("SystemAdmin")
    b = body()
    dt = parse_dt(b.get("to_iso8601"))
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Missing or invalid required field: to_iso8601")
    CLOCK.set(dt)
    tick()
    return ok_object({}, 200)
