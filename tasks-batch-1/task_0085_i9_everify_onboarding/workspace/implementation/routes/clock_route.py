"""Test-driving deterministic clock endpoint (PRD §3.7)."""

from flask import Blueprint

from errors import err
from middleware import require_roles
from response import object_response
from validation import get_json_body, require_str
from clock import clock as server_clock, parse_iso8601, format_iso8601

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles({"ComplianceOfficer"})
    body = get_json_body()
    require_str(body, "to_iso8601")
    try:
        dt = parse_iso8601(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601")
    server_clock.set(dt)
    return object_response({"current_utc": format_iso8601(dt)})
