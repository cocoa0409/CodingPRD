"""Logical clock test-driving endpoint."""

from flask import Blueprint

from auth import require_roles
from envelope import ok_object
from errors import invalid_request
import store
from util import body_or_empty, parse_iso_datetime, req_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(["DealerAdmin"])
    body = body_or_empty()
    raw = req_field(body, "to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise invalid_request("Field to_iso8601 must be an ISO 8601 datetime")
    store.set_clock(dt)
    return ok_object({"current_utc": store.clock_now_iso()}, 200)
