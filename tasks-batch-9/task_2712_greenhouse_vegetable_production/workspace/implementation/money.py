"""Decimal helpers. All monetary / weight / concentration arithmetic uses Decimal
with ROUND_HALF_UP -- never binary floating point, never banker's rounding."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 40

ZERO = Decimal("0")


def D(v):
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("bool is not a number")
    return Decimal(str(v))


def quant(v, places):
    exp = Decimal(1).scaleb(-places)
    return D(v).quantize(exp, rounding=ROUND_HALF_UP)


def q0(v):
    return quant(v, 0)


def q1(v):
    return quant(v, 1)


def q2(v):
    return quant(v, 2)


def q3(v):
    return quant(v, 3)


def q4(v):
    return quant(v, 4)


def dmin(a, b):
    a, b = D(a), D(b)
    return a if a <= b else b


def dmax(a, b):
    a, b = D(a), D(b)
    return a if a >= b else b


def to_int(v):
    return int(q0(v))
