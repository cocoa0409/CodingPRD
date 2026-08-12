"""Monitoring cycle checkpoint + logical clock control."""
from flask import Blueprint

import db
from errors import invalid_request
from middleware import body, require_field, require_roles
from response import success_obj
from services.cap import run_cycle

bp = Blueprint("monitoring", __name__)


@bp.post("/fair-lending/monitoring/run-cycle")
@require_roles("ComplianceDirector")
def monitoring_run_cycle():
    result = run_cycle()
    return success_obj(result)


@bp.post("/_clock/set_current_utc")
@require_roles("BankAdmin")
def set_clock():
    data = body()
    to_iso8601 = require_field(data, "to_iso8601")
    try:
        current = db.set_clock(to_iso8601)
    except (ValueError, TypeError):
        raise invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    return success_obj({"current_utc": current})
