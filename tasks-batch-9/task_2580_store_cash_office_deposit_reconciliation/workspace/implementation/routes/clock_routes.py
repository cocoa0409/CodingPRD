"""Test-driving logical clock endpoint (PRD section 2.4)."""
from flask import Blueprint

import clock
import response
import validation
from auth import ROLES, endpoint
from errors import err

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ROLES)
def set_current_utc():
    data = validation.body()
    requested = validation.req_datetime(data, "current_utc")
    if requested < clock.now():
        raise err("ERR_CLOCK_MONOTONIC", "the clock may only move forward")
    clock.set_now(requested)
    return response.object_response({"current_utc": clock.fmt(clock.now())})
