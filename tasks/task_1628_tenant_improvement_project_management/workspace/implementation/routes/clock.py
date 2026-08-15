"""POST /_clock/set_current_utc — logical clock control."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object
from errors import invalid_request
from services.util import parse_iso8601, to_iso_z

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not to_iso or not isinstance(to_iso, str):
        raise invalid_request("to_iso8601 is required and must be a string")
    try:
        dt = parse_iso8601(to_iso)
    except Exception:
        raise invalid_request("to_iso8601 is not a valid ISO8601 datetime")
    store.set_clock(to_iso_z(dt))
    return success_object({"current_utc": store.clock_iso()})
