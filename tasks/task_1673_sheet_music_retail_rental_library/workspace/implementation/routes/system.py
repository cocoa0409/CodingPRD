"""System capabilities: logical clock and daily sweep (LibraryAdmin only;
exempt from the priority-1 header check)."""
from datetime import timedelta
from flask import Blueprint

from db import clock
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_system
from response import success_object
from services import run_daily_sweep
from util import fmt_ts0, parse_instant
from routes.helpers import body

bp = Blueprint("system", __name__)


@bp.post("/library/_clock/set_current_utc")
def set_clock():
    require_system()
    data = body()
    target = parse_instant(data.get("to_iso8601"))
    if target is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO 8601 instant")
    clock["now"] = target
    return success_object({"current_utc": fmt_ts0(clock["now"])})


@bp.post("/library/_sweep/run_daily")
def sweep():
    require_system()
    return success_object(run_daily_sweep())
