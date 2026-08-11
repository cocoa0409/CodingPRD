"""Test-driving logical clock endpoint."""

from flask import Blueprint

from db import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles, get_json_body
from response import success_object
from util import iso_seconds, parse_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("SchedulingAdmin")
    body = get_json_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 is required")
    try:
        dt = parse_datetime(to_iso)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    db.clock = dt
    return success_object({"current_utc": iso_seconds(db.clock)})
