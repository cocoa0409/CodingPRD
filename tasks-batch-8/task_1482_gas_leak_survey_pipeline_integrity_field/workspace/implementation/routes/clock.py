"""Logical-clock test-driving endpoint (PRD §2.4)."""
from db import fmt_dt, now, set_clock
from middleware import body, req_dt, require_roles
from response import success
from services import process_time_based_events
from . import bp


@bp.post("/_clock/set_current_utc")
@require_roles("IntegrityAnalyst")
def set_current_utc():
    d = body()
    target = req_dt(d, "to_iso8601")
    set_clock(target)
    process_time_based_events()
    return success({"current_utc": fmt_dt(now())})
