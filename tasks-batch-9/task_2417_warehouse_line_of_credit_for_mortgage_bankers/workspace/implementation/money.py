"""Monetary and rate arithmetic.

PRD 2.5: every monetary quantity is an integer count of cents; every rate is a
decimal carried to four decimal places.  Rounding direction is deliberately
non-uniform:

* rate x principal  -> floored (truncated toward zero)
* a stored/shown rate -> rounded half up to four decimal places
* fee accrual        -> rounded half up to whole cents, per line
* covenant arithmetic -> pure integer cents, no rounding

Exact rational arithmetic (``fractions.Fraction`` built from ``decimal.Decimal``)
is used everywhere so that no intermediate binary-floating rounding can creep
into a comparison the PRD declares exact (notably the concentration solve of
PRD 3.4 step six).
"""

import math
from decimal import Decimal
from fractions import Fraction

ZERO = Fraction(0)


def frac(value):
    """Exact Fraction for a stored rate / integer amount."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        return Fraction(int(value))
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(Decimal(repr(value)))
    if isinstance(value, str):
        return Fraction(Decimal(value))
    raise TypeError("unsupported numeric %r" % (value,))


def floor_cents(value):
    """Floor an exact quantity to whole cents (truncation toward zero for the
    non-negative magnitudes this system produces)."""
    return math.floor(frac(value))


def round_half_up_cents(value):
    """Round an exact quantity half up to whole cents."""
    f = frac(value)
    if f >= 0:
        return math.floor(f + Fraction(1, 2))
    return -math.floor(-f + Fraction(1, 2))


def round_half_up_rate(value, places=4):
    """Round an exact rate half up to ``places`` decimal places."""
    scale = 10 ** places
    f = frac(value) * scale
    if f >= 0:
        return Fraction(math.floor(f + Fraction(1, 2)), scale)
    return Fraction(-math.floor(-f + Fraction(1, 2)), scale)


def rate_out(value):
    """Serialise a rate for JSON output."""
    if value is None:
        return None
    if isinstance(value, Fraction):
        return float(value)
    return value
