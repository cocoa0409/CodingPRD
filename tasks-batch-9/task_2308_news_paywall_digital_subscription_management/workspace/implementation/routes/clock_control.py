"""The test-driving logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

import config
import validation as v
from clock import clock, parse_datetime
from errors import fail
from middleware import auth
from response import object_response

bp = Blueprint("clock_control", __name__)


@bp.post("/_clock/set_current_utc")
@auth(*config.ALL_ROLES)
def set_current_utc():
    data = v.body()
    raw = data.get("current_utc")
    v.require_present(data, "current_utc")
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "Field 'current_utc' must be an RFC3339 UTC timestamp.")
    value = parse_datetime(raw)
    if value is None:
        fail("ERR_INVALID_REQUEST", "Field 'current_utc' must be an RFC3339 UTC timestamp.")
    if value < clock.now():
        fail("ERR_CLOCK_NOT_MONOTONIC")
    clock.set(value)
    return object_response({"current_utc": raw})
