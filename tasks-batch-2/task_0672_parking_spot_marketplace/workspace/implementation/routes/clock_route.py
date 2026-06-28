"""Logical clock setter.

PRD §2.9: accepts an ISO 8601 UTC instant in `to_iso8601` and advances the logical
clock. Advancing the clock may make reserved bookings whose window has fully elapsed
*eligible* to be marked as no-shows (the marking itself is the explicit mark-no-show
endpoint / system action; the clock-set only advances time).
"""
from flask import Blueprint, request

from clock import clock
from errors import err, ERR_INVALID_REQUEST
from middleware import get_caller, VALID_ROLES
from response import success
from util import require_body, require_field, parse_iso8601

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # Open endpoint (Anonymous or PlatformAdmin). If headers are present they must be
    # well-formed; but auth is not required to set the clock.
    role = request.headers.get("X-User-Role")
    if role is not None:
        # Tolerate well-formed Anonymous/PlatformAdmin; reject nothing here since the
        # endpoint is open to Anonymous.
        pass
    data = require_body(request.get_json(silent=True))
    raw = require_field(data, "to_iso8601")
    dt = parse_iso8601(raw)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 UTC instant.")
    clock.set(dt)
    return success({}, status=200)
