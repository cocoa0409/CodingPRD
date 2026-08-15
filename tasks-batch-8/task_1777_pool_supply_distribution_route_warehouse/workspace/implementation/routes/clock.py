"""Logical clock endpoint (PRD 2.6)."""
from flask import Blueprint

from middleware import get_caller, require_roles
from response import success_object
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/pool-supply/_clock/set_current_utc")
def set_clock():
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    dt = CLOCK.set(to_iso8601)
    from util import fmt_dt
    return success_object({"current_utc": fmt_dt(dt)})
