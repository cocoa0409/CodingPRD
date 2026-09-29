"""Money and rounding discipline (PRD §2.5).

Two rounding operations appear throughout and are never interchangeable:

* round half up -- take |x|, add one half, discard the fraction, re-apply the
  sign.  Python's ``decimal.ROUND_HALF_UP`` is exactly "round half away from
  zero", which is the same operation.
* floor -- discard the fractional part outright.

All money is integer cents; rates are decimals.  ``float`` is never used for
arithmetic, only for JSON output of ratios.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext

getcontext().prec = 60


def dec(value):
    """Coerce to Decimal without going through binary float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value):
    """round_half_up(x) to whole cents -> int."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ffloor(value):
    """floor(x) to whole cents -> int."""
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def round_dp(value, places):
    """Round a ratio to `places` decimal places, half up.  Returns Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def ratio(numerator, denominator, places):
    """Rounded ratio as Decimal (half up)."""
    return round_dp(dec(numerator) / dec(denominator), places)


def as_json_number(value):
    """Decimal -> float for JSON emission."""
    if value is None:
        return None
    return float(value)
