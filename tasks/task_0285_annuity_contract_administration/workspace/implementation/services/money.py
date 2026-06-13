"""Money / rounding primitives (PRD §2.7).

All amounts are integer cents. Where a calculation produces a fractional cent
the rule states whether to round-half-up (away from zero on the half) or floor.
We use decimal.Decimal so we never hit IEEE-754 drift.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) -> int. Half always rounds away
    from zero to the next whole cent (PRD §2.7)."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_decimal(value):
    """Round a Decimal value to a whole integer, half away from zero."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    """floor(numerator / denominator) -> int (mathematical floor)."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.to_integral_value(rounding=ROUND_FLOOR))
