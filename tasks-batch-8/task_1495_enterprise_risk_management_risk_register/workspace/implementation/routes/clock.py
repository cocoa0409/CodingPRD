"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

from db import set_clock, clock_now
from middleware import authenticate
from response import ok_object
from services import sweep_clock
from util import json_body, req_dt, fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("RiskManager",))
    data = json_body()
    target = req_dt(data, "to_iso8601")
    set_clock(target)
    # advancing the clock sweeps overdue plans and lapsed accepted breaches
    sweep_clock()
    return ok_object({"current_utc": fmt_dt(clock_now())})
