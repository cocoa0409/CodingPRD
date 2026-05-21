from ..store import store
from .bonus import compute_bonus_tier


def _rider_assignments_for(rider_id):
    return [a for a in store.assignments.values() if a["rider_id"] == rider_id]


def recompute_on_time_rate(rider):
    """Fraction of last 30 DELIVERED assignments that were on-time."""
    delivered = [a for a in _rider_assignments_for(rider["id"]) if a["status"] == "DELIVERED"]
    delivered.sort(key=lambda x: x.get("delivered_at") or x["created_at"])
    if len(delivered) < 10:
        rider["on_time_rate"] = 1.0
        return
    window = delivered[-30:]
    on_time = 0
    for a in window:
        order = store.orders.get(a["order_id"])
        if order is None:
            continue
        if (order.get("minutes_late") or 0) == 0:
            on_time += 1
    rider["on_time_rate"] = max(0.0, min(1.0, on_time / len(window)))


def recompute_acceptance_rate(rider):
    """Fraction of last 30 offers that were ACCEPTED (vs REJECTED)."""
    outcomes = [a for a in _rider_assignments_for(rider["id"])
                if a["status"] in ("ACCEPTED", "PICKED_UP", "DELIVERED", "REJECTED", "CANCELLED")]
    # Acceptance counts only ACCEPTED and REJECTED outcomes per PRD.
    # ACCEPTED includes everything advanced past ACCEPTED; CANCELLED was originally accepted.
    relevant = []
    for a in outcomes:
        if a["status"] == "REJECTED":
            relevant.append(("R", a))
        elif a["status"] in ("ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"):
            relevant.append(("A", a))
    relevant.sort(key=lambda x: x[1].get("accepted_at") or x[1].get("rejected_at") or x[1]["created_at"])
    if len(relevant) < 10:
        rider["acceptance_rate"] = 1.0
        return
    window = relevant[-30:]
    accepted = sum(1 for kind, _ in window if kind == "A")
    rider["acceptance_rate"] = max(0.0, min(1.0, accepted / len(window)))


def recompute_bonus_tier(rider):
    rider["bonus_tier"] = compute_bonus_tier(
        rider.get("on_time_rate", 1.0),
        rider.get("acceptance_rate", 1.0),
        rider.get("rating", 5.0),
    )
