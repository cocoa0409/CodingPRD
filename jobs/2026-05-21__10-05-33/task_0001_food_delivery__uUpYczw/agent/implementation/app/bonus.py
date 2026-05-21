"""Rider performance metrics and bonus_tier recomputation.

The PRD §3.3 specifies rolling windows of 30 events for on_time_rate
(completed deliveries) and acceptance_rate (offer outcomes). To support
these rolling windows we keep two private lists on each rider record:
  - `_offer_history`: append-only list of bools, True if accepted.
  - `_on_time_history`: append-only list of bools, True if delivered on time.

These are deliberately not part of the public response body; they live on
the in-memory record only.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


_WINDOW = 30
_MIN_COMPLETED_FOR_ON_TIME = 10


def _ensure_histories(rider: dict) -> None:
    rider.setdefault("_offer_history", [])
    rider.setdefault("_on_time_history", [])


def recompute_rider_metrics_on_offer_outcome(store, rider: dict, *, accepted: bool) -> None:
    _ensure_histories(rider)
    rider["_offer_history"].append(bool(accepted))
    window = rider["_offer_history"][-_WINDOW:]
    if not window:
        rider["acceptance_rate"] = 1.0
        return
    rate = sum(1 for x in window if x) / len(window)
    rider["acceptance_rate"] = max(0.0, min(1.0, rate))


def on_delivery_completed(store, rider: dict, *, was_on_time: bool) -> None:
    _ensure_histories(rider)
    rider["_on_time_history"].append(bool(was_on_time))
    completed = len(rider["_on_time_history"])
    if completed < _MIN_COMPLETED_FOR_ON_TIME:
        rider["on_time_rate"] = 1.0
        return
    window = rider["_on_time_history"][-_WINDOW:]
    rate = sum(1 for x in window if x) / len(window)
    rider["on_time_rate"] = max(0.0, min(1.0, rate))


def recompute_bonus_tier(rider: dict) -> None:
    score = (
        Decimal(str(rider["on_time_rate"])) * Decimal("0.6")
        + Decimal(str(rider["acceptance_rate"])) * Decimal("0.3")
        + (Decimal(str(rider["rating"])) / Decimal("5")) * Decimal("0.1")
    )
    score = score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    s = float(score)
    if s >= 0.900:
        tier = "PLATINUM"
    elif s >= 0.800:
        tier = "GOLD"
    elif s >= 0.700:
        tier = "SILVER"
    else:
        tier = "BRONZE"
    rider["bonus_tier"] = tier
