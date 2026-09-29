"""Decimal helpers.  Money is integer cents; every other scaled quantity is a
Decimal quantised with ROUND_HALF_UP unless the PRD pins a different mode."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def D(v):
    if isinstance(v, Decimal):
        return v
    if isinstance(v, float):
        return Decimal(repr(v))
    return Decimal(str(v))


def q(v, places):
    if v is None:
        return None
    exp = Decimal(1).scaleb(-places)
    return D(v).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(v):
    """round-half-up to a whole integer"""
    return int(D(v).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(v):
    return int(D(v).to_integral_value(rounding=ROUND_FLOOR))


def fnum(v, places=None):
    """Serialise a Decimal for JSON output."""
    if v is None:
        return None
    d = D(v) if places is None else q(v, places)
    return float(d)


def scale_of(v):
    d = D(v)
    exp = d.as_tuple().exponent
    return -exp if exp < 0 else 0
