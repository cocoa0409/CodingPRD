"""Test-driving logical clock endpoint."""

from flask import Blueprint

from db import clock_dt, set_clock
from helpers import body_dict, req_datetime, fmt_dt
from middleware import authenticate, authorize, AGENCY_DIRECTOR
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _uid, role = authenticate()
    authorize(role, {AGENCY_DIRECTOR})
    d = body_dict()
    to = req_datetime(d, "to_iso8601")
    set_clock(to)
    return success_object({"current_utc": fmt_dt(clock_dt())}, 200)
