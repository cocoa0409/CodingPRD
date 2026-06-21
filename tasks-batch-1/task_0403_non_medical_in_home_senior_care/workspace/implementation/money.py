"""Monetary precision helpers (PRD §2.8). round-half-up to 2 decimals."""
from decimal import Decimal, ROUND_HALF_UP


def D(x):
    """Coerce to Decimal via str to avoid binary float artifacts."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round_half_up(x, places=2):
    """Round to `places` decimal places using ROUND_HALF_UP. Returns a float
    carrying exactly `places` decimals (e.g. 30.0 -> 30.0, stored as 30.0)."""
    q = Decimal(1).scaleb(-places)  # 10**-places
    val = D(x).quantize(q, rounding=ROUND_HALF_UP)
    return float(val)


def round_int_half_up(x):
    """Round a quotient to the nearest whole number, halves going up."""
    return int(D(x).quantize(Decimal(1), rounding=ROUND_HALF_UP))
