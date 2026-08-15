"""Test-driving logical clock (PRD 2.5)."""
from flask import Blueprint

import db
from helpers import touch
from middleware import require_roles
from response import success
from util import fmt_clock
from validators import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
@require_roles("ProjectManager")
def set_current_utc():
    body = get_body()
    now = req_datetime(body, "to_iso8601")
    db.set_clock(now)
    # Automatic time-based transitions (PRD 3.3, 3.5):
    # LockoutWindow SCHEDULED -> EXPIRED when now >= ends_at, else -> ACTIVE in window.
    for w in db.lockout_windows.values():
        if w["status"] != "SCHEDULED":
            continue
        if now >= w["_ends_dt"]:
            w["status"] = "EXPIRED"
            touch(w)
        elif w["_starts_dt"] <= now < w["_ends_dt"]:
            w["status"] = "ACTIVE"
            touch(w)
    # LiftPermit ISSUED -> EXPIRED when now >= lift_ends_at.
    for l in db.lift_permits.values():
        if l["status"] == "ISSUED" and now >= l["_ends_dt"]:
            l["status"] = "EXPIRED"
            touch(l)
    return success({"current_utc": fmt_clock(db.clock_now())})
