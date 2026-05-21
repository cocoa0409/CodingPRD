"""Clock-advance + periodic sweep (test-only PlatformAdmin endpoints)."""
from __future__ import annotations

from datetime import timedelta

from core.clock import logical_now
from core.store import store
from core.utils import parse_iso
from services.calculations import (
    ADVERSE_LOCK_WINDOW_DAYS,
    recompute_eligibility_posture,
)
from services.timestamps import stamp_update


def run_sweep() -> dict:
    """Promote orders whose cooling-off has elapsed, and demote LOCKED
    candidates whose 365-day window has expired.
    """
    promoted = []
    demoted = []
    now = logical_now()

    for order_id, flow_id in list(store.adverse_flow_by_order.items()):
        flow = store.adverse_flows.get(flow_id)
        order = store.orders.get(order_id)
        if flow is None or order is None:
            continue
        if order["status"] != "PRE_ADVERSE_ISSUED":
            continue
        if flow["procedural_status"] != "PRE_AWAITING_DISPUTE_WINDOW":
            continue
        # No open dispute?
        from services.order_service import _any_open_dispute  # local import to avoid cycle

        if _any_open_dispute(order_id):
            continue
        try:
            eligible = parse_iso(flow["earliest_final_eligible_at"])
        except Exception:
            continue
        if now < eligible:
            continue
        # Promote.
        flow["procedural_status"] = "READY_FOR_FINAL"
        stamp_update(flow)
        order["status"] = "AWAITING_FINAL"
        stamp_update(order)
        promoted.append(order_id)

    # Demote candidates whose LOCKED window has expired.
    threshold = now - timedelta(days=ADVERSE_LOCK_WINDOW_DAYS)
    for cand in store.candidates.values():
        if cand.get("eligibility_posture") != "LOCKED":
            continue
        prev_posture = cand["eligibility_posture"]
        recompute_eligibility_posture(cand)
        if cand["eligibility_posture"] != prev_posture:
            stamp_update(cand)
            demoted.append(cand["id"])

    return {"promoted_orders": promoted, "demoted_candidates": demoted}
