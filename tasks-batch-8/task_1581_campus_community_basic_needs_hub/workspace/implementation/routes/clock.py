"""Logical clock + sweep checkpoint endpoints (PRD 2.4)."""
from flask import Blueprint

from middleware import authenticate, authorize
from response import success_object
from services.sweep import run_sweeps
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    # Advancing the clock does NOT itself fire automatic transitions.
    return success_object({"current_utc": CLOCK.current_utc_display()})


@bp.post("/_sweeps/run_pending_transitions")
def run_sweep_checkpoint():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    tallies = run_sweeps()
    return success_object(tallies)
