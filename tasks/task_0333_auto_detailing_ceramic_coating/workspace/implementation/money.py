"""Monetary arithmetic — integer cents, round-half-up at each multiplication (PRD §2.6)."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) -> int. Inputs are integers."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, bps):
    """round_half_up(amount_cents * bps / 10000) -> int."""
    return round_half_up(amount_cents * bps, 10000)
