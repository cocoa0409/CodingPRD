"""Logical clock endpoint (test-driving capability)."""
from flask import Blueprint

from db import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles, body
from response import success
from util import parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("MeterOpsAdmin")
    data = body()
    raw = data.get("to_iso8601")
    if raw is None:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required", 400)
    try:
        db.clock = parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime", 400)
    return success({}, response_type="object", code=200)
