"""Logical clock control (test-driving)."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role, get_json_body
from response import success
from services import common

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    to_iso8601 = common.require_string(body, "to_iso8601")
    target = db.parse_iso(to_iso8601)
    if target is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 datetime.")
    # The clock may only move forward.
    if target < db.now():
        raise ApiError(errors.ERR_CLOCK_NOT_MONOTONIC, 422, "Target time is earlier than the current clock.")
    db.set_clock(target)
    return success({}, 200)
