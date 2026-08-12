"""Logical clock test-driving endpoint (TerminalManager only)."""
from flask import Blueprint

from clock import CLOCK, _parse_iso, iso_z
from errors import err
from middleware import require_roles
from response import success_object
from validation import get_body

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("TerminalManager")
    body = get_body()
    raw = body.get("to_iso8601")
    dt = _parse_iso(raw)
    if dt is None:
        raise err("ERR_VALIDATION",
                  "Field 'to_iso8601' must be a valid ISO 8601 datetime")
    CLOCK.set(dt)
    return success_object({"current_utc": iso_z(CLOCK.now())})
