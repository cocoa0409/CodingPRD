"""Clock endpoint."""
from flask import Blueprint, request

from middleware import get_context, require_roles, get_json_body
from response import ok, error as error_response
from errors import ApiError
from services import clock as clock_svc

bp = Blueprint("misc", __name__)


@bp.route("/coop/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = get_context()
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not to_iso8601:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 is required")
    result = clock_svc.set_clock(to_iso8601)
    return ok(result)
