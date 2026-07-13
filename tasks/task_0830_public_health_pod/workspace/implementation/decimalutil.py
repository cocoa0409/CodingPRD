"""Decimal-precise rounding helpers. Never use float for money/scored figures."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING


def round_half_up(value, decimals: int):
    q = Decimal(1).scaleb(-decimals)  # e.g. decimals=2 -> Decimal('0.01')
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    if decimals == 0:
        return int(d)
    return float(d)


def floor_div(numerator, denominator) -> int:
    """Integer floor division on Decimals, avoiding float error."""
    n = Decimal(str(numerator))
    d = Decimal(str(denominator))
    return int((n / d).to_integral_value(rounding=ROUND_FLOOR))


def ceil_value(value) -> int:
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_CEILING))
