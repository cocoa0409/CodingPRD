"""Logical clock control (PRD §2.8, §4)."""
from flask import Blueprint

import errors
from clock import clock, parse_iso
from middleware import get_identity, require_roles
from response import object_response
from services import common

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Still requires PlatformAdmin even though it is system-maintenance (PRD §2.1, §4).
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin"})
    body = common.get_body()
    to_iso = common.require_str(body, "to_iso8601")
    try:
        parse_iso(to_iso)
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 timestamp.")
    now_iso = clock.set(to_iso)
    return object_response({"now_iso": now_iso})
