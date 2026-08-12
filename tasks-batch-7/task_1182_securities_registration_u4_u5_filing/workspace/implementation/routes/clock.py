"""Logical clock endpoint (SystemOperator)."""
from flask import Blueprint

from db import store
from middleware import auth
from common import body
from response import success_obj
from errors import err_invalid_request
from timeutil import parse_dt
from services import sweep_clock

bp = Blueprint("clock", __name__)


@bp.post("/registration-desk/_clock/set_current_utc")
def set_current_utc():
    auth("SystemOperator")
    data = body()
    raw = data.get("to_iso8601")
    if raw is None or not isinstance(raw, str):
        raise err_invalid_request("to_iso8601 is required and must be an ISO 8601 timestamp")
    dt = parse_dt(raw)
    if dt is None:
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    store.clock = dt
    store.clock_echo = raw
    sweep_clock()
    return success_obj({"current_utc": store.clock_echo}, 200)
