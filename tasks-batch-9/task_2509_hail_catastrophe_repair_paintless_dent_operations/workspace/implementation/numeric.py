"""Decimal helpers. All money is whole cents and every rounding is round half up."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING


def D(value):
    """Exact Decimal from an int/float/str without binary float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round half up. Returns int when places == 0, else Decimal."""
    quantum = Decimal(1).scaleb(-places)
    result = D(value).quantize(quantum, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(result)
    return result


def ceil_int(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def frac(value):
    d = D(value)
    return d - int(d.to_integral_value(rounding="ROUND_FLOOR"))
