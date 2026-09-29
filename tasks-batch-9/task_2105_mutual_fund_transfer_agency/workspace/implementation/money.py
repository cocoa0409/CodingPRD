"""Decimal helpers.  All money/share/price arithmetic uses Decimal with ROUND_HALF_UP."""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")


def D(value):
    """Coerce a JSON-ish numeric into Decimal without float contamination."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def q(value, places):
    if value is None:
        return None
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def q4(value):
    return q(value, 4)


def num(value, places):
    """Render a Decimal for JSON at the declared precision."""
    if value is None:
        return None
    return float(q(value, places))


def decimal_places(value):
    """Number of decimal places a JSON number carries."""
    d = D(value)
    exponent = d.as_tuple().exponent
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)
