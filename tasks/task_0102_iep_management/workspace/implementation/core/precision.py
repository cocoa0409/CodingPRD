"""Decimal precision helpers — round_half_up at the precision the SCAFFOLD defines."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value, places: int):
    """Round value (Decimal/float/int) to `places` decimal places using ROUND_HALF_UP.

    Returns a float for places >= 1 (so JSON serialises as a number),
    and an int for places == 0.
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(rounded)
    return float(rounded)
