"""Test-support logical clock endpoint (PRD 2.5)."""

from flask import Blueprint

import clock as logical_clock
import validation as v
from middleware import ALL_ROLES, roles
from response import fmt_ts, object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@roles(*ALL_ROLES)
def set_current_utc():
    body = v.Body()
    moment, raw_value = body.timestamp("to_iso8601")
    logical_clock.set_now(moment, raw_value)
    echo = raw_value if raw_value is not None else fmt_ts(moment)
    return object_response({"current_utc": echo})
