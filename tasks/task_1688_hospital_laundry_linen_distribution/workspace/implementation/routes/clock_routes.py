"""Logical-clock test-driving endpoint (PRD 2.5)."""
from flask import Blueprint

import clock
from auth import authenticate, authorize
from errors import ERR_INVALID_REQUEST, raise_err
from util import body_json, fmt_ts, parse_iso_datetime, req_str, success_object

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    body = body_json()

    raw = req_str(body, "to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    clock.set_current(dt)
    return success_object({"current_utc": fmt_ts(clock.now())}, 200)
