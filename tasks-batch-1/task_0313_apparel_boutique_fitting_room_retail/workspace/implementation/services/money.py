"""Monetary precision helpers (PRD §2.6). Integer cents, round-half-up away from zero."""
from decimal import Decimal, ROUND_HALF_UP

MIN_PRICE_CENTS = 100


def round_half_up(numerator, denominator):
    """Round (numerator / denominator) half-up to the nearest integer.

    Ties round away from zero to the larger magnitude (PRD §2.6).
    Inputs are exact integers; Decimal keeps the division exact before rounding.
    """
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
