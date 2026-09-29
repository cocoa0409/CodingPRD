"""Precision discipline of PRD section 2.8.

Every quantity in this API is one of four shapes: whole cents, whole basis
points, a two-decimal percentage, or a whole-second instant.  All arithmetic
here runs through `decimal.Decimal`; Python's built-in `round()` is never used
because it rounds half to even.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

ZERO = Decimal(0)
CENT_EXP = Decimal(1)
PCT_EXP = Decimal("0.01")


def D(value):
    """Exact Decimal from an int, str or Decimal (never from a float)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def half_up_cents(value):
    """Whole cents, round half up: the API-wide default for money."""
    return int(D(value).quantize(CENT_EXP, rounding=ROUND_HALF_UP))


def ceiling_cents(value):
    """Whole cents, rounded up whenever any fraction remains."""
    return int(D(value).quantize(CENT_EXP, rounding=ROUND_CEILING))


def half_up_bp(value):
    """Whole basis points, round half up (`percent_funded_bp`)."""
    return int(D(value).quantize(CENT_EXP, rounding=ROUND_HALF_UP))


def truncate_bp(value):
    """Whole basis points with the fraction discarded, never rounded."""
    sign = -1 if D(value) < 0 else 1
    return sign * int(abs(D(value)))


def pct2(value):
    """A percentage carried to exactly two decimal places, round half up."""
    return D(value).quantize(PCT_EXP, rounding=ROUND_HALF_UP)


def ratio_pct(count, denominator):
    """100 * count / denominator, computed once from exact integers."""
    if denominator == 0:
        return pct2(0)
    return pct2(D(100) * D(count) / D(denominator))


def number(value):
    """Render a Decimal as a JSON number."""
    return float(D(value))


# --- exact rational helpers ------------------------------------------------
# Several computations hold their intermediate terms as exact fractions (the
# suitability weights, the reserve per-component shares, the interest shares)
# and round exactly once at the end.  Rounding a Fraction directly keeps the
# half-way case exact instead of relying on a decimal quotient's tail.

def half_up_frac(fraction):
    """Round an exact Fraction half up to a whole unit."""
    numerator, denominator = fraction.numerator, fraction.denominator
    if denominator == 1:
        return numerator
    doubled = 2 * numerator
    floor_value = numerator // denominator
    remainder_twice = doubled - 2 * floor_value * denominator
    if remainder_twice >= denominator:
        return floor_value + 1
    return floor_value


def ceiling_frac(fraction):
    """Round an exact Fraction up to the next whole unit."""
    numerator, denominator = fraction.numerator, fraction.denominator
    floor_value = numerator // denominator
    if floor_value * denominator == numerator:
        return floor_value
    return floor_value + 1


def pct2_frac(fraction):
    """A two-decimal percentage from an exact Fraction, rounded half up once."""
    hundredths = half_up_frac(fraction * 100)
    return D(hundredths).scaleb(-2)
