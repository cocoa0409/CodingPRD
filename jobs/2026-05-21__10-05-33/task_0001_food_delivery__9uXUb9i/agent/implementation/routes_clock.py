"""Clock advance endpoint (PRD §2.10)."""
from __future__ import annotations

from flask import Blueprint

from auth import require_roles
from common import get_json_body, require_number
from envelope import success
from errors import ApiError
from serializers import serialize_assignment
import store
from store import advance_clock, iso_z, lock, now


bp = Blueprint("clock", __name__, url_prefix="/api/_clock")


def _parse_iso(s: str):
    from datetime import datetime
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


@bp.post("/advance")
@require_roles("PlatformAdmin")
def advance():
    body = get_json_body()
    seconds = require_number(body, "seconds")
    if seconds < 0:
        raise ApiError("ERR_VALIDATION", "seconds must be non-negative.")
    with lock():
        advance_clock(seconds)
        # Sweep OFFERED Assignments older than 60s -> REJECTED, then redispatch.
        from routes_assignments import _recompute_acceptance_rate, _recompute_bonus_tier
        from dispatch import open_dispatch_offer

        cur = now()
        swept = []
        for a in list(store.assignments.values()):
            if a["status"] != "OFFERED":
                continue
            age = (cur - _parse_iso(a["offered_at"])).total_seconds()
            if age >= 60:
                a["status"] = "REJECTED"
                rider = store.riders.get(a["rider_id"])
                if rider:
                    hist = store.rider_history.setdefault(
                        rider["id"], {"deliveries": [], "offers": [], "ratings": []}
                    )
                    hist["offers"].append({"accepted": False, "assignment_id": a["id"]})
                    _recompute_acceptance_rate(rider)
                    _recompute_bonus_tier(rider)
                    rider["updated_at"] = iso_z(cur)
                    rider["version"] += 1
                swept.append(a)
        for a in swept:
            order = store.orders.get(a["order_id"])
            if order is None:
                continue
            if order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
                # Don't redispatch if some other live assignment already covers it.
                has_live = any(
                    other["order_id"] == order["id"]
                    and other["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
                    for other in store.assignments.values()
                )
                if not has_live:
                    open_dispatch_offer(order, raise_on_empty=False)

    return success({"swept": [serialize_assignment(a) for a in swept]})
