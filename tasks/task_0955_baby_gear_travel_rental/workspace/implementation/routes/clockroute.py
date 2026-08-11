from flask import Blueprint

import clock
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj
from util import fmt_clock, parse_dt

bp = Blueprint("clockroute", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("OperationsAdmin")
    b = body()
    dt = parse_dt(b.get("to_iso8601"))
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO 8601 instant")
    clock.set_current(dt)
    return ok_obj({"current_utc": fmt_clock(clock.now_dt())})
