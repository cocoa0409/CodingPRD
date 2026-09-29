"""Money helpers. All amounts are integer cents; rounding is always half up."""
from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def pct_out(value):
    """Serialize a rate/percentage as a JSON number."""
    if value is None:
        return None
    return float(value)
