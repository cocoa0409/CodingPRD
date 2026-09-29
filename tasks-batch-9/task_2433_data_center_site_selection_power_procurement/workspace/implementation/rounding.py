"""Half-up rounding helpers (PRD 2.7).

All rounding in the system is half-up; monetary amounts carry 2 decimals, MW and
MWh 3 decimals, percentages 2 decimals, workforce_availability_ratio 4.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

# Plenty of head-room for intermediate division / exponentiation.
getcontext().prec = 60

ZERO = Decimal("0")


def q(value, places):
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def q4(value):
    return q(value, 4)


def dec(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
