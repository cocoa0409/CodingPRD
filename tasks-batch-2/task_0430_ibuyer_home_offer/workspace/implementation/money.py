"""Monetary precision helpers (PRD §2.5): 2 dp, round-half-up (away from zero)."""

from decimal import Decimal, ROUND_HALF_UP


def D(value):
    """Coerce an int/float/str/Decimal into Decimal without float artifacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # repr-based conversion preserves the human-intended literal
        return Decimal(repr(value))
    return Decimal(str(value))


def round2(value):
    """Round to 2 decimal places, half-up (away from zero). Returns a float."""
    d = D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)
