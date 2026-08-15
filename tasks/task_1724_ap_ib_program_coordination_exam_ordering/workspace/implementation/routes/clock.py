"""Logical clock endpoint (PRD 2.4). Every advance runs the expiry sweep first."""
from flask import Blueprint

from middleware import get_caller, require_roles
from response import success_object
from services.sweep import run_expiry_sweep
from util import CLOCK, fmt_dt
from validate import get_body, reject_unknown_fields, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller = require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"to_iso8601"})
    to_dt = req_datetime(body, "to_iso8601")
    new_dt = CLOCK.set(fmt_dt(to_dt))
    run_expiry_sweep(new_dt)
    return success_object({"current_utc": fmt_dt(new_dt)})
