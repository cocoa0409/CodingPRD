"""Test-driving logical clock endpoint (PlatformAdmin only)."""
from flask import Blueprint, request

import clock
from errors import validation
from middleware import require_roles
from response import success_object
from util import parse_datetime, fmt_ts

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    target = body.get("to_iso8601")
    dt = parse_datetime(target, "to_iso8601")
    clock.set_current(dt)
    return success_object({"current_utc": fmt_ts(clock.now())})
