"""Money / decimal precision helpers — half-up rounding."""

from decimal import Decimal, ROUND_HALF_UP


def half_up_int(value) -> int:
    """Round value (number or Decimal) half-up to nearest integer."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def half_up_one_decimal(value) -> float:
    """Round value half-up to one decimal place; return as float."""
    d = Decimal(str(value))
    q = d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)
