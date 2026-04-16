from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def round_half_up(value):
    """Round to nearest integer with half-up rule."""
    if isinstance(value, (int,)):
        return int(value)
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round to 2 decimal places with half-up rule; returns float."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    result = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(result)


def floor_mul(a, b):
    """Floor of a * b where a is int (cents) and b is numeric rate, returning int."""
    da = Decimal(a)
    db = Decimal(str(b))
    product = da * db
    return int(product.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def mul_round_half_up(a, b):
    """round_half_up(a * b)"""
    da = Decimal(a)
    db = Decimal(str(b))
    product = da * db
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
