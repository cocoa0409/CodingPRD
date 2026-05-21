from datetime import datetime, timedelta, timezone

from ..store import store
from ..repository import now_iso
from .dispatch import dispatch_offer


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def sweep_expired_offers():
    """Any Assignment in OFFERED for >= 60 seconds becomes REJECTED, and a fresh offer is issued."""
    from ..app import logical_clock
    now = logical_clock.now()
    threshold = timedelta(seconds=60)
    to_reject = []
    for a in list(store.assignments.values()):
        if a["status"] != "OFFERED":
            continue
        offered_at = _parse_iso(a["offered_at"])
        if (now - offered_at) >= threshold:
            to_reject.append(a)
    # Sort by offered_at to keep deterministic order
    to_reject.sort(key=lambda x: x["offered_at"])
    for a in to_reject:
        a["status"] = "REJECTED"
        a["rejected_at"] = now_iso()
        rider = store.riders.get(a["rider_id"])
        if rider is not None:
            from .rider_metrics import recompute_acceptance_rate, recompute_bonus_tier
            from ..repository import touch
            recompute_acceptance_rate(rider)
            recompute_bonus_tier(rider)
            touch(rider)
        order = store.orders.get(a["order_id"])
        if order is not None and order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            dispatch_offer(order)
