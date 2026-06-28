"""Logical clock endpoint."""
from flask import Blueprint

from clock import clock, parse_iso8601, format_iso8601
from middleware import require_roles
from response import object_response
from validation import get_body, invalid

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("System")
def set_clock():
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        invalid("Field 'to_iso8601' is required and must be an ISO 8601 string")
    dt = parse_iso8601(raw)
    if dt is None:
        invalid("Field 'to_iso8601' must be a valid ISO 8601 timestamp")
    clock.set(dt)
    return object_response({"now": format_iso8601(clock.now)}, status=200)
