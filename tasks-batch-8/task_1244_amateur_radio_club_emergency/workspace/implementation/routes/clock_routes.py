"""Logical clock endpoint (PRD §2.5). This is the single unauthenticated
surface of the API: the §2.1 header checks do not apply to it."""
from flask import Blueprint, request

import db
import services as svc
from response import success
from util import as_dt, body_json, need, reject_unknown_fields

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    body = body_json(request)
    reject_unknown_fields(body, {"to_iso8601"})
    dt = as_dt(need(body, "to_iso8601"), "to_iso8601")
    db.set_now(dt)
    # Setting the clock fires the fixed sweep of system transitions (PRD §2.5).
    svc.clock_sweep()
    return success({}, "object", 200)
