"""Logical clock endpoint."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/api/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    to_iso8601 = payload.get("to_iso8601")
    if not to_iso8601 or not isinstance(to_iso8601, str):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        dt = db.parse_iso(to_iso8601)
    except Exception:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    db.set_clock(dt)
    return success_object({"current_utc": db.iso_now()})
