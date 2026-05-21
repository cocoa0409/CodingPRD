"""Rider bonus tier computation."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def compute_bonus_tier(on_time_rate: float, acceptance_rate: float, rating: float) -> str:
    """Half-up rounding to 3 decimals; inclusive lower-bound mapping."""
    s = (Decimal(str(on_time_rate)) * Decimal("0.6")
         + Decimal(str(acceptance_rate)) * Decimal("0.3")
         + (Decimal(str(rating)) / Decimal("5")) * Decimal("0.1"))
    rounded = s.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if rounded >= Decimal("0.900"):
        return "PLATINUM"
    if rounded >= Decimal("0.800"):
        return "GOLD"
    if rounded >= Decimal("0.700"):
        return "SILVER"
    return "BRONZE"
