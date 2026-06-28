"""Logical-clock test-driving control (PRD §2.4)."""
from flask import Blueprint

from clock import clock, parse_iso8601, to_iso8601_millis
from common import bad_request, get_json_body
from middleware import get_user_context, require_role
from response import success_object

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    body = get_json_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise bad_request("to_iso8601 is required.")
    try:
        dt = parse_iso8601(raw)
    except (ValueError, TypeError):
        raise bad_request("to_iso8601 is not a valid ISO 8601 timestamp.")
    clock.set(dt)
    return success_object({"current_utc": to_iso8601_millis(clock.now())})
