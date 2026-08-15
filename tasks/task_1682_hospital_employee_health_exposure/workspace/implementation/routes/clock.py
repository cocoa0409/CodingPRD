"""Logical clock endpoint (system-level, outside the /employee-health prefix)."""
from flask import Blueprint

from db import clock
from errors import ApiError
from middleware import auth, body, require_role
from response import success_object
from services.sweep import run_sweep
from util import fmt_dt, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    to_dt = parse_dt(data.get("to_iso8601"))
    if to_dt is not None and to_dt <= clock.current:
        raise ApiError(
            "ERR_CLOCK_REGRESSION",
            "to_iso8601 must be strictly after the current logical time",
        )
    if to_dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp")
    clock.current = to_dt
    transitions_applied = run_sweep()
    return success_object(
        {"current_utc": fmt_dt(clock.current), "transitions_applied": transitions_applied}
    )
