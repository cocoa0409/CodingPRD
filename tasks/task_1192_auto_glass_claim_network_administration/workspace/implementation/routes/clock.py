"""Test-driving logical clock (NetworkAdmin only)."""

from flask import Blueprint

from db import store, iso, parse_dt
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import get_context, body_json, req_str, ROLE_NETWORK_ADMIN
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    get_context([ROLE_NETWORK_ADMIN])
    data = body_json(required=True)
    raw = req_str(data, "to_iso8601")
    try:
        dt = parse_dt(raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 datetime")
    store.clock = dt
    return success_object({"current_utc": iso(store.clock)})
