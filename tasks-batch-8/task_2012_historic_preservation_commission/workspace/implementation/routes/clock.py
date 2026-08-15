"""Test-driving logical clock endpoint (PRD 2.5)."""
from flask import Blueprint

from middleware import get_caller, check_role_allowed, ALL_ROLES
from response import success_object
from util import CLOCK, fmt_dt
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__, url_prefix="/preservation")


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller = get_caller()
    body = get_body()
    to_dt = req_datetime(body, "to_iso8601")
    check_role_allowed(caller, ALL_ROLES)
    CLOCK.set(to_dt)
    return success_object({"current_utc": fmt_dt(CLOCK.now())})
