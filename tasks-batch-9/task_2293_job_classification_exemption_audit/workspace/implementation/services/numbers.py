"""Rounding primitives (PRD 2.11)."""
from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up: nearest unit, a value ending in exactly one half goes
    away from zero. places=1 rounds to the nearest tenth."""
    d = dec(value)
    exponent = Decimal(1).scaleb(-places)
    q = d.quantize(exponent, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(q)
    return q


def floor_div(numerator, denominator):
    """floor(numerator / denominator) for integers."""
    return numerator // denominator


def num_out(value):
    """Render a numeric domain value for JSON."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return float(value)
        return float(value)
    return value


def clamp(low, high, value):
    return max(low, min(high, value))
