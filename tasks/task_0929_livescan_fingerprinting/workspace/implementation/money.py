"""Money arithmetic.  Every amount is an integer number of whole cents and every
percentage product is rounded to whole cents on its own, by round-half-up,
before it enters any sum (PRD 2.8)."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(value):
    """value is a Decimal (or int); returns an int number of whole cents."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(pct, amount_cents):
    return round_half_up_cents(Decimal(pct) * Decimal(int(amount_cents)))


def round_half_up_2dp(value):
    """The one non-money quantity: mean_quality_score, two decimals, half up."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
