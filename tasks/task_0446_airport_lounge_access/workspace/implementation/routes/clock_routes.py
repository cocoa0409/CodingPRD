"""Logical-clock test-driving endpoint (PRD §2.4)."""
from flask import Blueprint

import clock
from middleware import get_principal, require_role
from validation import get_json_body, require_str
from response import success
import errors

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = clock.parse_iso(to_iso)
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant")
    clock.set_now(dt)
    return success({"now": clock.now_iso_millis()})
