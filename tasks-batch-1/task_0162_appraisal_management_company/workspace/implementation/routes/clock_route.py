"""Test-driving clock endpoint (PlatformAdmin only)."""
from flask import Blueprint

import clock
import errors
import middleware
import response
from services import validate

bp = Blueprint("clock_route", __name__)


@bp.route("/amc/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"PlatformAdmin"})
    data = validate.body()
    to_iso = validate.require(data, "to_iso8601")
    parsed = clock.parse_iso(to_iso)
    if parsed is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 timestamp.")
    clock.set_pinned(parsed)
    return response.ok_object({}, 200)
