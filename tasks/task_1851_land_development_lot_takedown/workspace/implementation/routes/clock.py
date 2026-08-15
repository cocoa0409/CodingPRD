"""Logical clock test-driving endpoint (PRD 2.5)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from services.cascades import clock_sweep
from util import CLOCK, parse_dt
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["DeveloperOperator"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    new_dt = parse_dt(to_iso8601)
    CLOCK.set(new_dt)
    # Setting the clock fires time-based system transitions (contingency
    # auto-expiry) and re-anchors trailing absorption windows.
    clock_sweep(new_dt)
    return success_object({"current_utc": CLOCK.now_iso()})
