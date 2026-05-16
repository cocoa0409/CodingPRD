"""Money math helpers.

All monetary values are stored as integer USD cents. When a calculation
multiplies a cents amount by a rate, the resulting product is rounded half-up
to the nearest whole cent before being used downstream.
"""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(cents: int, rate) -> int:
    """Multiply integer cents by rate (Decimal or float) and round half-up to int cents."""
    if not isinstance(rate, Decimal):
        rate = Decimal(str(rate))
    product = Decimal(int(cents)) * rate
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
