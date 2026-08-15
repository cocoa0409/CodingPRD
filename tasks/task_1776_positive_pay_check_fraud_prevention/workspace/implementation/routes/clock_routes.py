"""Logical-clock test-driving endpoint (PRD §2.5). BankOps only."""
from flask import Blueprint

import clock
from auth import authenticate, authorize
from errors import ERR_INVALID_REQUEST, raise_err
from util import body_json, parse_iso_datetime, success_object

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role, _user = authenticate()
    authorize(role, _user, ["BankOps"])
    body = body_json()
    raw = body.get("to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 UTC timestamp")
    clock.set_current(dt, raw.strip())
    return success_object({"current_utc": clock.literal()}, 200)
