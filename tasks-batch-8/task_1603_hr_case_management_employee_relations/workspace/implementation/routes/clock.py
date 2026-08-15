"""Logical clock endpoint (PRD §2.5)."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorize
from response import success_object
from util import CLOCK, fmt_dt, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/er/_clock/set_current_utc")
def set_current_utc():
    authorize({"ERManager"})
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    to_iso8601 = body.get("to_iso8601")
    if to_iso8601 is None:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        new_dt = parse_dt(to_iso8601)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    CLOCK._dt = new_dt
    return success_object({"current_utc": fmt_dt(CLOCK.now())})
