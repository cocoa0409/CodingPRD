"""Logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

from middleware import get_caller, check_role
from response import success_object
from util import CLOCK
from validate import get_body, check_allowed, req_datetime

bp = Blueprint("clock", __name__, url_prefix="/erate")


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, {"to_iso8601"})
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    return success_object({"current_utc": CLOCK.now_iso()})
