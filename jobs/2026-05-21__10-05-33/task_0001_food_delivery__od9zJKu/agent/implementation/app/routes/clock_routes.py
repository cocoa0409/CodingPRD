from __future__ import annotations

import datetime as _dt

from flask import Blueprint

from .. import assignment_logic
from ..auth import require_role
from ..clock import clock
from ..envelope import err_validation, success
from ..store import store
from ..validators import get_json, require_number

bp = Blueprint("clock_routes", __name__)


@bp.route("/api/_clock/advance", methods=["POST"])
def advance_clock():
    require_role("PlatformAdmin")
    body = get_json()
    seconds = require_number(body, "seconds")
    if seconds < 0:
        raise err_validation("seconds must be non-negative")
    clock.advance(float(seconds))
    # Sweep stale OFFERED assignments
    swept = _sweep_offer_timeouts()
    return success({"now": _now_iso(), "swept_assignments": swept})


def _sweep_offer_timeouts() -> int:
    """Move any OFFERED Assignment whose offered_at is more than 60s ago to REJECTED."""
    now = clock.now()
    swept = 0
    # Snapshot list because we mutate store during iteration via redispatch
    candidates = [
        a for a in list(store.assignments.values()) if a["status"] == "OFFERED"
    ]
    for a in candidates:
        offered_at = _dt.datetime.fromisoformat(a["offered_at"].replace("Z", "+00:00"))
        if (now - offered_at).total_seconds() >= 60:
            assignment_logic.timeout_sweep_assignment(a)
            swept += 1
    return swept


def _now_iso() -> str:
    from ..clock import iso_now
    return iso_now()
