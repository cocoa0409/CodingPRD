"""Fixed-precision arithmetic (PRD 2.7).

Every rounding operation in the platform is round-half-up, so no float ever
carries a money or capacity figure.
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal(0)

_QUANT = {
    0: Decimal(1),
    2: Decimal("0.01"),
    3: Decimal("0.001"),
    4: Decimal("0.0001"),
}


def dec(value):
    """Coerce to Decimal without going through binary float."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def q(value, places):
    """Round half up to `places` decimal places."""
    return dec(value).quantize(_QUANT[places], rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to whole cents and return an int."""
    return int(q(value, 0))


def num(value):
    """Render a Decimal for JSON as a plain number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        as_int = int(value)
        if value == as_int:
            return as_int
        return float(value)
    return value


def floor_minutes(seconds):
    """Whole minutes, partial minute discarded."""
    return int(seconds // 60)


def floor_days(seconds):
    """Whole days, partial day discarded."""
    return int(seconds // 86400)
