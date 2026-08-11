"""Integer-cent arithmetic. All rounding is half up, away from zero, per PRD 2.7."""

from decimal import Decimal, ROUND_HALF_UP


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal/number to a whole cent, half away from zero."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_to_step(value, step):
    """Round to the nearest multiple of `step` cents, half up."""
    quotient = D(value) / D(step)
    whole = quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(whole) * int(step)


def quantize_fraction(value, places=4):
    """Effective discount fractions are carried to four decimal places (PRD 2.7)."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)
