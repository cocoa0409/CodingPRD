"""Clock-advance endpoint with offer-timeout sweep."""
from __future__ import annotations

from flask import Blueprint

from .. import cascade
from ..auth import require_role
from ..bonus import recompute_bonus_tier, recompute_rider_metrics_on_offer_outcome
from ..clock import parse_iso
from ..dispatch import open_dispatch
from ..envelope import envelope_object, expect_json_body
from ..errors import ApiError
from ..store import get_clock, get_store

bp = Blueprint("clock", __name__, url_prefix="/api")


@bp.post("/_clock/advance")
def advance_clock():
    require_role({"PlatformAdmin"})
    body = expect_json_body()
    seconds = body.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ApiError("ERR_VALIDATION", "seconds must be a number")
    if seconds < 0:
        raise ApiError("ERR_VALIDATION", "seconds must be >= 0")

    store = get_store()
    clock = get_clock()
    with store.lock:
        clock.advance(float(seconds))
        # Sweep OFFERED assignments older than 60 seconds.
        now = clock.now_dt()
        for a in list(store.assignments.values()):
            if a["status"] != "OFFERED":
                continue
            offered_at = parse_iso(a["offered_at"])
            if (now - offered_at).total_seconds() >= 60:
                a["status"] = "REJECTED"
                rider = store.riders.get(a["rider_id"])
                if rider:
                    recompute_rider_metrics_on_offer_outcome(store, rider, accepted=False)
                    recompute_bonus_tier(rider)
                    cascade.touch(rider, clock)
                order = store.orders.get(a["order_id"])
                if order and order["status"] in {"RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"}:
                    open_dispatch(store, clock, order, force=True)
    return envelope_object({"now": clock.now_iso()})
