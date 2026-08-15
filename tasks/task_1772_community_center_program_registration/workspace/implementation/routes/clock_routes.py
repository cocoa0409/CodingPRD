"""POST /_clock/set_current_utc — test-driving logical clock (PRD 2.5)."""
from flask import Blueprint

import clock
from auth import authenticate, authorize
from errors import raise_err
from util import body_json, parse_iso_datetime, success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    raw = body.get("to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise_err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC timestamp")
    clock.set_current(dt)
    # The response echoes the operator-supplied reading as current_utc.
    return success_object({"current_utc": raw}, 200)
