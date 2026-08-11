"""Integer-cent arithmetic.  Rounding is always half-up, away from zero."""

from decimal import ROUND_HALF_UP, Decimal


def round_half_up(numerator, denominator=1):
    """round_half_up(numerator / denominator) -> int.

    A value whose fractional part is exactly one half rounds away from zero,
    to the larger magnitude (PRD 2.7).
    """
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
