"""The logical clock (PRD 2.5).  Never wall-clock time."""

from flask import Blueprint

from db import clock_iso, set_clock
from middleware import require
from response import object_response
from validation import body, f_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require(("PlatformAdmin",))
    payload = body()
    instant, raw = f_dt(payload, "current_utc", required=True)
    set_clock(instant, raw)
    return object_response({"current_utc": clock_iso()})
