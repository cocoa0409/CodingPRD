"""Test-driving logical clock (PRD 2.4)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from services.transitions import run_clock_sweep
from util import CLOCK
from validate import get_body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/infusion/_clock/set_current_utc")
def set_clock():
    authorized(["PolicyAdmin"])
    body = get_body()
    new_dt = req_dt(body, "to_iso8601")
    CLOCK.set_dt(new_dt)
    # Setting the clock synchronously applies all time-based transitions.
    run_clock_sweep(new_dt)
    return success_object({"current_utc": CLOCK.now_iso()})
