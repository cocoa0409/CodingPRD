"""Decimal arithmetic helpers. Round half up, never bankers' rounding."""
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

ZERO = Decimal("0")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def rhu(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def num(value, places):
    """Round half up and hand back a JSON number carrying the scale."""
    return float(rhu(value, places))


def divide(numerator, denominator):
    return dec(numerator) / dec(denominator)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))
