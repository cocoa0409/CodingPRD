"""Logical clock endpoint."""
from flask import Blueprint

import clock
from auth import authenticate, authorize
from errors import raise_err, ERR_INVALID_REQUEST
from util import body_json, req_datetime, success_object
import services

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    authorize(role, ["FleetManager"])
    body = body_json()
    dt = req_datetime(body, "to_iso8601")
    clock.set_current(dt)
    services.run_expiry_sweeps()
    return success_object({}, 200)
