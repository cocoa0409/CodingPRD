"""Logical clock test-driving endpoint (PRD section 2.6).

Mounted at the API root: the declared path is /_clock/set_current_utc with no
/homebuilder prefix.
"""

from flask import Blueprint

from middleware import authenticate
from response import success_obj
from util import body_json, check_shape, parse_dt
import db
import services

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["PlatformAdmin"])
    body = body_json()
    check_shape(body, {"to_iso8601": {"type": "datetime", "required": True}})
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    db.set_clock(dt)
    # Setting the clock deterministically executes the scheduled sweep at the
    # new instant: phase status re-derivation (lazy), expired reservation-hold
    # release, and contingency-deadline auto-cancellation.
    services.run_clock_sweep(dt)
    return success_obj({"current_utc": body["to_iso8601"]}, 200)
