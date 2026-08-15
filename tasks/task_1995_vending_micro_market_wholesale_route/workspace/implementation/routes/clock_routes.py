"""Logical clock endpoint (scaffold §1.5; PRD §2.5)."""
from flask import Blueprint
from middleware import get_auth, require_role
from response import success_object
from util import get_json_body, req_string
from errors import ApiError, ERR_INVALID_REQUEST
import clock

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["WholesaleAdmin"])
    raw = req_string(body, "to_iso8601")
    try:
        dt = clock.parse_iso(raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 datetime")
    clock.set_current(dt)
    return success_object({"current_utc": clock.format_iso(dt)})
