"""Numeric precision helpers (PRD 2.6): dollars 2dp, MWh 1dp, percentages 2dp,
all ROUND_HALF_UP, rounded at every step a formula names."""
from decimal import Decimal, ROUND_HALF_UP, localcontext

TWO = Decimal("0.01")
ONE = Decimal("0.1")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def q2(value):
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def q1(value):
    return dec(value).quantize(ONE, rounding=ROUND_HALF_UP)


def high_precision():
    ctx = localcontext()
    return ctx


def pow_1_03(years):
    """(1.03) ** years computed exactly."""
    factor = Decimal(1)
    step = Decimal("1.03")
    for _ in range(int(years)):
        factor = factor * step
    return factor


def to_json(value):
    if isinstance(value, Decimal):
        return float(value)
    return value
