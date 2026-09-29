"""Exact arithmetic helpers.  Every rounding operation is round-half-up."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

ZERO = Decimal(0)


def frac(value):
    """Coerce anything numeric into an exact Fraction."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(Decimal(str(value)))
    raise TypeError("not numeric: %r" % (value,))


def rhu(value, places=0):
    """Round half up (away from zero at the midpoint) to `places` decimals."""
    f = frac(value)
    with localcontext() as ctx:
        ctx.prec = 60
        dec = Decimal(f.numerator) / Decimal(f.denominator)
    quantum = Decimal(1).scaleb(-places)
    return dec.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dec(value, places):
    """Quantize a client-supplied number to its declared decimal places."""
    if isinstance(value, Decimal):
        base = value
    else:
        base = Decimal(str(value))
    return base.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def d2(value):
    return dec(value, 2)


def d4(value):
    return dec(value, 4)
