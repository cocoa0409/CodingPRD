"""Decimal helpers. PRD 2.8: all money/minute/percentage arithmetic uses
Decimal with ROUND_HALF_UP; trunk quantities round UP (ceiling)."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, localcontext

ZERO = Decimal("0")
D2 = Decimal("0.01")
D4 = Decimal("0.0001")
D6 = Decimal("0.000001")


def q(value, places):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


def q6(value):
    return q(value, 6)


def money(value):
    return q2(value)


def ceil_div(numerator, denominator):
    """Integer ceiling division on Decimals / ints."""
    if not isinstance(numerator, Decimal):
        numerator = Decimal(str(numerator))
    if not isinstance(denominator, Decimal):
        denominator = Decimal(str(denominator))
    with localcontext() as ctx:
        ctx.prec = 40
        ratio = numerator / denominator
    return int(ratio.to_integral_value(rounding=ROUND_CEILING))


def scale_of(value):
    """Number of decimal places carried by a Decimal literal."""
    exp = value.as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return max(0, -exp)
