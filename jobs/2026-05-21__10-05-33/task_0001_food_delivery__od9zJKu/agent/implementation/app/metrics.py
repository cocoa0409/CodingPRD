"""Rider metric recomputation: acceptance_rate, on_time_rate, rating, bonus_tier."""
from __future__ import annotations

import decimal
from decimal import Decimal


WINDOW = 30
MIN_DELIVERIES_FOR_ON_TIME = 10


def _round_half_up_3dp(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.001"), rounding=decimal.ROUND_HALF_UP)


def recompute_acceptance_rate(rider: dict) -> float:
    """Fraction of last 30 dispatch offers (ACCEPTED + REJECTED) that were ACCEPTED."""
    history = rider.setdefault("_offer_history", [])  # list of "ACCEPTED" or "REJECTED"
    if not history:
        return 1.0
    window = history[-WINDOW:]
    accepted = sum(1 for h in window if h == "ACCEPTED")
    return accepted / len(window)


def recompute_on_time_rate(rider: dict) -> float:
    """Last 30 completed (DELIVERED) deliveries; on_time iff not late.
    Initialized to 1.0 if fewer than 10 deliveries.
    """
    history = rider.setdefault("_delivery_history", [])  # list of bool (on_time)
    if len(history) < MIN_DELIVERIES_FOR_ON_TIME:
        return 1.0
    window = history[-WINDOW:]
    on_time = sum(1 for h in window if h)
    return on_time / len(window)


def recompute_rating(rider: dict) -> float:
    history = rider.setdefault("_rating_history", [])  # list of float ratings
    if not history:
        return 5.0
    window = history[-WINDOW:]
    return sum(window) / len(window)


def compute_bonus_tier(on_time_rate: float, acceptance_rate: float, rating: float) -> str:
    score = (
        Decimal(str(on_time_rate)) * Decimal("0.6")
        + Decimal(str(acceptance_rate)) * Decimal("0.3")
        + (Decimal(str(rating)) / Decimal("5")) * Decimal("0.1")
    )
    rounded = _round_half_up_3dp(score)
    s = float(rounded)
    if s >= 0.90:
        return "PLATINUM"
    if s >= 0.80:
        return "GOLD"
    if s >= 0.70:
        return "SILVER"
    return "BRONZE"


def recompute_all(rider: dict) -> None:
    rider["on_time_rate"] = max(0.0, min(1.0, recompute_on_time_rate(rider)))
    rider["acceptance_rate"] = max(0.0, min(1.0, recompute_acceptance_rate(rider)))
    rider["rating"] = max(0.0, min(5.0, recompute_rating(rider)))
    rider["bonus_tier"] = compute_bonus_tier(
        rider["on_time_rate"], rider["acceptance_rate"], rider["rating"]
    )
