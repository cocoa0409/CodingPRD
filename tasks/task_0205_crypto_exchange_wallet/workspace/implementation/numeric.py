"""Decimal precision helpers (§2.7). Never use float for money math."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING


def D(x):
    """Coerce a value to Decimal via its string form (avoids float artifacts)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("bool is not a number")
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(str(x))


def round_half_up(value, decimals):
    q = Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def round_up(value, decimals):
    q = Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)
    return D(value).quantize(q, rounding=ROUND_CEILING)


def round_usd(value):
    return round_half_up(value, 2)


def to_number(d):
    """Convert a Decimal to a JSON-friendly number (int when integral, else float)."""
    if not isinstance(d, Decimal):
        d = D(d)
    d = d.normalize()
    if d == d.to_integral_value():
        # Preserve integer-ness but avoid scientific notation surprises.
        return int(d)
    return float(d)


def decimals_of(value):
    """Number of fractional digits in the supplied numeric literal."""
    d = D(value)
    exponent = d.as_tuple().exponent
    if isinstance(exponent, int) and exponent < 0:
        return -exponent
    return 0
