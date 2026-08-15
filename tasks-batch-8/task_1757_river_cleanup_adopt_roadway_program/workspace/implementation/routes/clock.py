"""Logical clock endpoint (PRD 2.5): coordinator-only, strictly forward, and
every advance runs the four scheduled sweeps in their fixed order."""
from flask import Blueprint

from middleware import get_caller, check_role, COORD
from response import success_object
from services.sweep import run_sweeps
from util import CLOCK
from validate import get_body, req_datetime_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller = get_caller()
    check_role(caller, [COORD])
    body = get_body()
    to_iso8601 = req_datetime_str(body, "to_iso8601")
    CLOCK.set(to_iso8601)  # rejects a non-advancing move with ERR_INVALID_REQUEST
    run_sweeps()
    return success_object({"current_utc": CLOCK.now_iso()})
