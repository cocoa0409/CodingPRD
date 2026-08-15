"""Test-driving logical clock endpoint (PRD 2.5)."""
from flask import Blueprint

import clock
from auth import authenticate, authorize
from errors import ERR_INVALID_REQUEST, raise_err
from services import certificate_expiry_sweep
from util import body_json, fmt_ts, parse_iso_datetime, success_object

bp = Blueprint("clock", __name__)


@bp.route("/tea-ops/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    authorize(role, ["PlatformAdmin"])
    body = body_json()
    dt = parse_iso_datetime(body.get("to_iso8601"))
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 UTC timestamp")
    clock.set_current(dt)
    # Side effect: certificate expiry sweep.
    certificate_expiry_sweep()
    return success_object({"current_utc": fmt_ts(clock.now())}, 200)
