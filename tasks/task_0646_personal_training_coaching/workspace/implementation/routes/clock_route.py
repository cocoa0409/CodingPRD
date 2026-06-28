"""Logical-clock test-driving endpoint (PRD §2.4)."""

from flask import Blueprint

import errors
from clock import clock, parse_iso8601, format_iso8601_ms
from helpers import get_json_body, require_fields
from middleware import require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    body = get_json_body()
    require_fields(body, "to_iso8601")
    try:
        instant = parse_iso8601(body["to_iso8601"])
    except Exception:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant")
    clock.set(instant)
    return success({"current_utc": format_iso8601_ms(instant)}, 200)
