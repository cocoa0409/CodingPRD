"""The logical clock capability (PRD 2.4)."""

from flask import Blueprint

import auth
import clock
import validation
from envelope import ok

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require(auth.ANY)
    data = validation.body()
    instant, raw = validation.req_datetime(data, "current_utc")
    clock.set_now(instant, raw)
    return ok({"current_utc": clock.now_raw()})
