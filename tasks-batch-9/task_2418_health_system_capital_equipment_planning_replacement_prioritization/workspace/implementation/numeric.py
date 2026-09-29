"""Decimal arithmetic helpers — round half up everywhere (PRD section 2.5)."""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

TWO = Decimal("0.01")
ONE = Decimal("1")
ZERO2 = Decimal("0.00")
HUNDRED = Decimal("100")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def r2(value):
    """Round half up to two fractional digits."""
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def r0(value):
    """Round half up to a whole number of cents."""
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def clamp2(value, low=Decimal("0.00"), high=Decimal("100.00")):
    value = r2(value)
    if value < low:
        return r2(low)
    if value > high:
        return r2(high)
    return value
