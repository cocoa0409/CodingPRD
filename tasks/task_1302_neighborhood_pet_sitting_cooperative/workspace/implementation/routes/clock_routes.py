"""POST /coop/_clock/set_current_utc — logical clock control (CoopAdmin)."""

from flask import Blueprint

import clock
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import body, require_roles
from response import ok
from services.cascade import expire_requests
from util import fmt_dt, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/coop/_clock/set_current_utc")
def set_current_utc():
    require_roles("CoopAdmin")
    data = body()
    raw = data.get("to_iso8601")
    try:
        target = parse_dt(raw)
    except (TypeError, ValueError):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO 8601 datetime"
        )
    clock.set_now(target)
    expire_requests()
    return ok({"current_utc": fmt_dt(clock.now())})
