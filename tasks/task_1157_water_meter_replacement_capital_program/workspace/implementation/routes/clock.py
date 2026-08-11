"""Test-driving logical clock (PRD 2.4). ProgramManager only."""
import db
from db import clock_now, fmt_ts, set_clock
from middleware import require_roles
from response import ok_object
from flask import Blueprint
from validate import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
@require_roles("ProgramManager")
def set_current_utc():
    b = body()
    to = req_dt(b, "to_iso8601")
    set_clock(to)
    return ok_object({"current_utc": fmt_ts(clock_now())})
