"""Logical clock test-driving capability (ParkAdmin only)."""
from flask import Blueprint

from db import store
from errors import ApiError, ERR_INVALID_REQUEST
from helpers import get_body, req_string, parse_datetime, now_iso
from middleware import require_auth
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/dog-park/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_auth(["ParkAdmin"])
    body = get_body()
    raw = req_string(body, "to_iso8601")
    target = parse_datetime(raw)
    if target is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_iso8601 must be an ISO 8601 UTC instant")
    store.clock = target
    return ok({"current_utc": now_iso()})
