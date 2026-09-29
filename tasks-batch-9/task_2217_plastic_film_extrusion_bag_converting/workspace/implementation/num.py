"""Decimal helpers.  All rounding in this system is round-half-up (PRD §2.5)."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext

getcontext().prec = 60

ZERO = Decimal("0")


def D(x):
    """Coerce to Decimal without going through binary float artefacts."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def r(x, places):
    """Round half up to `places` decimals, returning a Decimal."""
    if x is None:
        return None
    return D(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def f(x, places=None):
    """Round (optionally) and return a JSON-friendly float."""
    if x is None:
        return None
    if places is not None:
        x = r(x, places)
    return float(x)


def floor_div(a, b):
    """floor(a / b) as an int, computed in Decimal space."""
    a, b = D(a), D(b)
    if b == 0:
        return 0
    return int((a / b).to_integral_value(rounding=ROUND_FLOOR))


def floor_int(a):
    return int(D(a).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int_div(a, b):
    """ceil(a / b) over integers."""
    a, b = int(a), int(b)
    if b == 0:
        return 0
    return -((-a) // b)


def dsqrt(x):
    return D(x).sqrt()
