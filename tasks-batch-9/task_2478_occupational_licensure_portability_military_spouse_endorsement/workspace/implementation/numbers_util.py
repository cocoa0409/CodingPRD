"""Rounding discipline (PRD §2.5).  Money is integer cents; scores are two
decimal places and requirement hours one decimal place, all rounded half up."""
from decimal import Decimal, ROUND_HALF_UP

ONE = Decimal("1")
TENTH = Decimal("0.1")
HUNDREDTH = Decimal("0.01")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu2(value):
    return rhu(value, 2)


def rhu1(value):
    return rhu(value, 1)


def rhu_cents(value):
    """Round half up to a whole cent, returning an int."""
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def to_json_number(value):
    """Render a Decimal for JSON without introducing binary drift."""
    if value is None:
        return None
    return float(value)
