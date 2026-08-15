"""Logical clock route."""
from flask import Blueprint, request

import db
import middleware
import response
import util

bp = Blueprint("clock", __name__)


@bp.route("/deice-ops/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.require_roles("StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["to_iso8601"])
    dt = util.parse_iso(payload["to_iso8601"], "to_iso8601")
    db.set_clock(dt)
    # Echo back with millisecond precision and trailing Z.
    current = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return response.success_object({"current_utc": current}, 200)
