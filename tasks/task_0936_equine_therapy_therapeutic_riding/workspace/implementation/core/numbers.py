"""Money / weight / hours arithmetic.  Decimal only - never float (PRD §2.6)."""

from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def round2(value):
    """Weights and service hours: 2 decimal places, round-half-up."""
    return float(round_half_up(value, 2))


def cents(value):
    """Money: whole cents, round-half-up."""
    return int(round_half_up(value, 0))


def minutes_to_hours(minutes):
    """§2.6 - the ONE route from minutes to hours: /60 then round to 2dp."""
    return round2(dec(minutes) / Decimal(60))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)
