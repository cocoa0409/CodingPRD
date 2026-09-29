"""Numeric helpers. All rounding in this system is round-half-up (PRD 2.7)."""
from decimal import Decimal, ROUND_HALF_UP


def D(value):
    """Coerce to Decimal without ever going through binary float arithmetic."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def is_number(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def decimal_places(value):
    exp = D(value).normalize().as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return max(0, -exp)
