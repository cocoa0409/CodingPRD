"""The logical clock (PRD 2.4)."""

from flask import Blueprint

from db import now, set_clock
from middleware import authenticate
from routes._common import send_data
from timeutil import fmt
from valid import body, req_ts

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate("PlatformAdmin")
    payload = body()
    instant = req_ts(payload, "to_iso8601")
    set_clock(instant)
    return send_data({"current_utc": fmt(now())})
