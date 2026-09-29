"""Logical clock control (PRD 2.4)."""
from flask import Blueprint

import clock
import config
import middleware
import response
import validate

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require(config.ALL_ROLES)
    body = validate.body()
    current_utc = validate.req_dt(body, "current_utc")
    clock.set_now(current_utc)
    return response.object_response({"current_utc": response.iso_instant(current_utc)})
