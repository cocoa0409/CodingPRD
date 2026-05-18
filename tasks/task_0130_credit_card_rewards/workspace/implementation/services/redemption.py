"""Statement-credit redemption math.

POINTS_FIRST: points_debited = requested_points
              credit_amount_cents = floor(requested_points * 100 / POINTS_PER_DOLLAR_TIER)
AMOUNT_FIRST: credit_amount_cents = requested_amount_cents
              points_debited = ceil(requested_amount_cents * POINTS_PER_DOLLAR_TIER / 100)
"""
from __future__ import annotations

from constants import POINTS_PER_DOLLAR


def points_first(requested_points: int, tier: str) -> tuple[int, int]:
    """Return (points_debited, credit_amount_cents)."""
    ratio = POINTS_PER_DOLLAR[tier]
    credit_cents = (requested_points * 100) // ratio  # floor
    return requested_points, credit_cents


def amount_first(requested_amount_cents: int, tier: str) -> tuple[int, int]:
    """Return (points_debited, credit_amount_cents)."""
    ratio = POINTS_PER_DOLLAR[tier]
    # ceil(a / b) = (a + b - 1) // b for positive a, b
    num = requested_amount_cents * ratio
    points_debited = (num + 100 - 1) // 100
    return points_debited, requested_amount_cents
