"""Monetary precision helpers (PRD §2.6).

round_half_up: a value whose fractional part is exactly one half rounds away
from zero to the next whole cent. floor_div: truncation toward zero, used by
the credit-decision rules.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric (cents) value half-up to an integer."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_mul(cents, rate):
    """floor(cents * rate) using exact Decimal arithmetic (truncate toward zero)."""
    d = Decimal(str(cents)) * Decimal(str(rate))
    # floor toward zero; cents and rate are non-negative throughout the spec.
    return int(d.to_integral_value(rounding="ROUND_FLOOR"))
