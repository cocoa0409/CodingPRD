"""Precision helpers (PRD §2.7).

All money is integer cents. Fractional cents round half-up (away from zero on a
.5 tie). Volume/weight conversions carry their own stated decimal precision
before any cent rounding. We use decimal.Decimal with ROUND_HALF_UP — never
float — for every rounding boundary.
"""
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 50


def D(value):
    """Build a Decimal from int/float/str/Decimal without IEEE-754 noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    # str(float) gives the shortest round-trip decimal, avoiding 0.1+0.2 noise
    return Decimal(str(value))


def round_half_up(value, dp=0):
    """Round a value half-up to `dp` decimal places. Returns a Decimal.
    For dp == 0 the caller typically wraps in int()."""
    quant = Decimal(1).scaleb(-dp)  # 10^-dp
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round to whole cents (half-up) and return a Python int."""
    return int(round_half_up(value, 0))


def to_number(dec):
    """Convert a Decimal that may carry fractional places into a JSON-friendly
    number: an int when it is integral, else a float."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)
