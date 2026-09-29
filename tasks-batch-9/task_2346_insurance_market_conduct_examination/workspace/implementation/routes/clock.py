"""The logical clock (PRD §2.4): set the instant and sweep overdue data calls."""

from flask import Blueprint

import validation as v
from db import set_clock
from middleware import clock_authorize
from response import success
from services import transitions

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@clock_authorize
def set_current_utc():
    payload = v.body()
    raw, parsed = v.parse_rfc3339_utc(payload, "to_iso8601")
    set_clock(parsed)
    swept = transitions.sweep_overdue_data_calls(parsed.strftime("%Y-%m-%d"))
    return success({"current_utc": raw, "data_calls_flagged_overdue": swept})
