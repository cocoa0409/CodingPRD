"""Cent arithmetic helpers (PRD §2.6): integer cents, round half up."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value, places=0):
    """Round a Decimal/int/float-free value half up to `places` decimals."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole number of cents and return an int."""
    return int(round_half_up(value, 0))
