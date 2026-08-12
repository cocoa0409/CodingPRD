"""POST /_clock/set_current_utc — logical clock control."""
from flask import Blueprint, request
import db
from middleware import require_roles, get_json_body
from response import success_object
from errors import ApiError, ERR_INVALID_REQUEST

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_roles("PlatformAdmin")
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not to_iso8601:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required", 400)
    dt = db._parse_iso(to_iso8601)
    if not dt:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid ISO 8601 datetime", 400)
    db.set_clock(dt)
    return success_object({"current_utc": db._to_iso(dt)})
