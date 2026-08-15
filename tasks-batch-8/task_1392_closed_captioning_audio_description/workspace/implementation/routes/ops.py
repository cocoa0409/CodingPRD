"""Test-driving / ops endpoints (PRD §2.7): the logical clock and the sweep."""
from flask import Blueprint

from auth import body, guarded
from db import CLOCK
from respond import ok_object
from services import workflow
from util import fmt_dt, req_dt

bp = Blueprint("ops", __name__)


@bp.post("/caption-ad/_clock/set_current_utc")
@guarded({"OperationsManager"})
def set_current_utc(_user_id, _role):
    to = req_dt(body(), "to_iso8601")
    CLOCK.set(to)
    return ok_object({"current_utc": fmt_dt(CLOCK.now())})


@bp.post("/caption-ad/_ops/run-sweep")
@guarded({"OperationsManager"})
def run_sweep(_user_id, _role):
    counts = workflow.run_sweep()
    return ok_object(counts)
