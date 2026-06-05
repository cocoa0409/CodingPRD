"""Logical clock control endpoints (PRD §2.8, §3.9).

Both are reserved exclusively for SystemAdmin. They still require valid auth
headers; only the SystemAdmin role is permitted.
"""
from flask import Blueprint

import db
import errors
import validate
from middleware import authenticate, authorize
import response
import clock
from services import calc

bp = Blueprint("clock_ctl", __name__)


@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    p = authenticate()
    authorize(p, {"SystemAdmin"})
    data = validate.body()
    to_iso8601 = validate.require_str(data, "to_iso8601")
    try:
        dt = clock.parse_iso(to_iso8601)
    except ValueError:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 instant.")
    db.CLOCK.set_to(dt)
    return response.object_response({"clock_now": db.CLOCK.now_iso()})


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    p = authenticate()
    authorize(p, {"SystemAdmin"})
    data = validate.body()
    hours = validate.require_int(data, "hours")
    db.CLOCK.advance_hours(hours)
    breached_ids, escalations_created = calc.sla_breach_sweep()
    return response.object_response({
        "clock_now": db.CLOCK.now_iso(),
        "breached_request_ids": breached_ids,
        "escalations_created": escalations_created,
    })
