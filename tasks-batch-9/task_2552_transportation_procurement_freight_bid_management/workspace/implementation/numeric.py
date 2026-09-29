"""Decimal helpers.  PRD §2.7: all money is 2dp, per-mile rates 4dp, percentages 2dp,
claims_ratio 4dp, optimisation ratios 6dp, service credit 4dp; rounding is ROUND_HALF_UP
everywhere and the rounding *order* is normative."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, InvalidOperation

ZERO = Decimal("0")


def D(value):
    """Coerce an input value into Decimal without losing supplied precision."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        return Decimal(value.strip())
    raise InvalidOperation("not a number")


def rnd(value, places):
    """Round half up to `places` decimal places."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return rnd(value, 2)


def q4(value):
    return rnd(value, 4)


def q6(value):
    return rnd(value, 6)


def rnd_int(value):
    """Round half up to a whole number (returns int)."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value):
    """Largest whole number not exceeding value."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_FLOOR))
