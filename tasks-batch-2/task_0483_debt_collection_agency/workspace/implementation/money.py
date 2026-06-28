"""Monetary rounding helpers (PRD 2.6): integer cents, round-half-up."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(numerator, denominator):
    """Compute numerator / denominator and round to a whole integer, half up.

    numerator and denominator are integers (cents * bps, divided by 10000, etc.).
    """
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
