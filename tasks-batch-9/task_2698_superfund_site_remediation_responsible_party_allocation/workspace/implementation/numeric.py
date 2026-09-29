"""Exact arithmetic helpers.

Money is always an integer count of cents; percentages, concentrations and
risks are Decimals carried at their declared scale.  Every rounding in the
specification is ROUND HALF UP (away from zero), so it is implemented once
here over exact rationals and never delegated to float.
"""

from decimal import Decimal
from fractions import Fraction

ZERO = Decimal("0")


def frac(value):
    """Coerce anything numeric into an exact Fraction."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    return Fraction(str(value))


def rhu(value, places):
    """Round half up (away from zero) to `places` decimals, exactly."""
    f = frac(value)
    scale = 10 ** places
    scaled = f * scale
    num, den = scaled.numerator, scaled.denominator
    if num >= 0:
        q = (2 * num + den) // (2 * den)
    else:
        q = -((-2 * num + den) // (2 * den))
    if places == 0:
        return Decimal(q)
    return Decimal(q).scaleb(-places)


def rhu_cents(value):
    """Round half up to whole cents, as an int."""
    return int(rhu(value, 0))


def pct(value):
    """Round half up to the 2 decimal places every percentage in the spec uses."""
    return rhu(value, 2)


def dec2(value):
    """Quantise an already-exact value to 2 decimals for output."""
    return rhu(value, 2)


def as_json_number(value):
    """Render a Decimal for the JSON body without ever going through float math."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return float(value)
