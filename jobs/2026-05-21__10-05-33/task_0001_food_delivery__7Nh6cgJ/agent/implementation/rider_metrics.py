"""Rider metric (acceptance_rate / on_time_rate) and bonus_tier recomputation."""

from __future__ import annotations

from bonus import compute_bonus_tier
from store import STORE


def recompute_acceptance_rate(rider: dict) -> None:
    """fraction of last 30 ACCEPTED+REJECTED dispatch offers that were ACCEPTED."""
    offers = [a for a in STORE.assignments.values()
              if a["rider_id"] == rider["id"] and a["status"] in ("ACCEPTED", "REJECTED",
                                                                    "PICKED_UP", "DELIVERED", "CANCELLED")]
    # Use offered_at to order — but our outcomes include the post-acceptance lifecycle.
    # Per PRD: union of ACCEPTED and REJECTED outcomes — interpret as offers whose terminal
    # outcome is one of accepted (anything that started with accept) or rejected.
    decided = []
    for a in offers:
        if a["status"] == "REJECTED":
            decided.append((a["offered_at"], "REJECTED"))
        elif a["status"] in ("ACCEPTED", "PICKED_UP", "DELIVERED"):
            decided.append((a["offered_at"], "ACCEPTED"))
        elif a["status"] == "CANCELLED":
            # Rider-initiated cancellation after acceptance is still an ACCEPTED offer.
            decided.append((a["offered_at"], "ACCEPTED"))
    decided.sort(key=lambda x: x[0])
    last30 = decided[-30:]
    if not last30:
        rider["acceptance_rate"] = 1.0
        return
    accepted = sum(1 for _, o in last30 if o == "ACCEPTED")
    rate = accepted / len(last30)
    rider["acceptance_rate"] = max(0.0, min(1.0, rate))


def recompute_on_time_rate(rider: dict) -> None:
    """fraction of last 30 DELIVERED assignments that arrived on or before promised time."""
    delivered = [a for a in STORE.assignments.values()
                 if a["rider_id"] == rider["id"] and a["status"] == "DELIVERED"]
    delivered.sort(key=lambda a: a.get("delivered_at") or "")
    last30 = delivered[-30:]
    if len(last30) < 10:
        rider["on_time_rate"] = 1.0
        return
    on_time = 0
    for a in last30:
        order = STORE.orders.get(a["order_id"])
        if order is None:
            continue
        minutes_late = order.get("minutes_late")
        if minutes_late is not None and minutes_late == 0:
            on_time += 1
    rate = on_time / len(last30)
    rider["on_time_rate"] = max(0.0, min(1.0, rate))


def recompute_bonus_tier(rider: dict) -> None:
    rider["bonus_tier"] = compute_bonus_tier(
        rider.get("on_time_rate", 1.0),
        rider.get("acceptance_rate", 1.0),
        rider.get("rating", 5.0),
    )
