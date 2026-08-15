"""Logical-clock administration (PRD 2.4)."""
from flask import Blueprint

from middleware import get_caller, locked, require_roles
from response import success_object
from util import CLOCK, fmt_dt
from validate import get_body, req_datetime_iso

bp = Blueprint("clock", __name__)

PM = ["ProgramManager"]


@bp.route("/_clock/set_current_utc", methods=["POST"])
@locked
def set_current_utc():
    caller = get_caller()
    body = get_body()
    to_iso8601 = req_datetime_iso(body, "to_iso8601")
    require_roles(caller, PM)
    dt = CLOCK.set(to_iso8601)
    return success_object({"current_utc": fmt_dt(dt)})
