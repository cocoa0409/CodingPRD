"""Exact decimal arithmetic helpers (PRD section 2.6).

Every rounding in this service is half-up: a value exactly at the midpoint rounds
away from zero. Square roots are evaluated to twelve decimal places before any
further arithmetic consumes them.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext, localcontext

getcontext().prec = 60

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)

Q0 = Decimal(1)
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
Q6 = Decimal("0.000001")
Q12 = Decimal("0.000000000001")


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if value is None:
        return None
    return Decimal(str(value))


def q(value, exponent):
    return D(value).quantize(exponent, rounding=ROUND_HALF_UP)


def q0(value):
    """Round to an exact integer, half-up."""
    return int(D(value).quantize(Q0, rounding=ROUND_HALF_UP))


def q2(value):
    return q(value, Q2)


def q4(value):
    return q(value, Q4)


def q6(value):
    return q(value, Q6)


def q12(value):
    return q(value, Q12)


def dsqrt(value):
    """Square root evaluated to twelve decimal places."""
    with localcontext() as ctx:
        ctx.prec = 60
        root = D(value).sqrt()
    return q12(root)
