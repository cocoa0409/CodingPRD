"""Precision helpers (PRD 2.8).  Money is integer cents, never float."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to whole cents and return an int."""
    return int(round_half_up(value, 0))


def pct1(value):
    """One decimal place, rounded half up, returned as a JSON number."""
    return float(round_half_up(value, 1))


def floor_div(numerator, denominator):
    if D(denominator) == 0:
        return 0
    return int((D(numerator) / D(denominator)).to_integral_value(rounding=ROUND_FLOOR))


def floor_of(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_div(numerator, denominator):
    if D(denominator) == 0:
        return 0
    return int((D(numerator) / D(denominator)).to_integral_value(rounding=ROUND_CEILING))
