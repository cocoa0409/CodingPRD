"""Monetary / numeric precision helpers (PRD section 2.6).

Every dollar figure is carried to exactly two decimal places using
ROUND_HALF_UP.  ara_percentage carries four decimals, rate_pct six.
"""
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

ZERO = Decimal("0.00")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def D(value):
    """Coerce anything numeric into a Decimal without float noise."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def q2(value):
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(value):
    return D(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q6(value):
    return D(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def dmax(a, b):
    a, b = D(a), D(b)
    return a if a >= b else b


def dmin(a, b):
    a, b = D(a), D(b)
    return a if a <= b else b
