"""Logical clock test-driving endpoint (PRD §2.7)."""

from flask import Blueprint

from db import CLOCK, parse_iso, format_ts
from errors import err_validation
from middleware import require_roles
from response import success
from services.helpers import body_json, require_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("ContestLead")
    body = body_json()
    value = require_field(body, "to_iso8601")
    if not isinstance(value, str):
        raise err_validation("to_iso8601 must be an ISO8601 timestamp string")
    try:
        dt = parse_iso(value)
    except (ValueError, TypeError):
        raise err_validation("to_iso8601 is not a valid ISO8601 timestamp")
    CLOCK.set(dt)
    return success({"current_utc": format_ts(CLOCK.now())})
