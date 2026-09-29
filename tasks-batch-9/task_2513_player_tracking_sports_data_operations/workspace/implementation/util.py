"""Shared numeric / temporal / serialization helpers.

PRD §2.7 defines three distinct numeric disciplines that must not be confused:
round-half-up to a fixed number of decimals, ceiling to the next whole unit, and
exact (unrounded) arithmetic.  Every continuous quantity in this module is
carried as ``fractions.Fraction`` so that a ceiling applied to a value that is
mathematically an exact integer never lands one unit too high.
"""

import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

ISO_FMT = "%Y-%m-%dT%H:%M:%S"


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime(ISO_FMT), dt.microsecond // 1000)


def now_real():
    return datetime.now(timezone.utc)


def iso_now():
    return iso(now_real())


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Exact arithmetic helpers
# --------------------------------------------------------------------------

def F(value):
    """Exact Fraction from an int / float / str / Decimal / Fraction."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    return Fraction(str(value))


def ceil_units(value):
    """Ceiling to the next whole unit (PRD §2.7 'Ceiling')."""
    return int(math.ceil(F(value)))


def round_half_up(value, places=0):
    """Round half up to ``places`` decimals, returning a Decimal.

    Half-way values move away from zero, which is what PRD §2.7 means by
    "rounded half up" for the non-negative figures this API stores.
    """
    frac = F(value)
    negative = frac < 0
    if negative:
        frac = -frac
    scaled = frac * (10 ** places)
    n, d = scaled.numerator, scaled.denominator
    q = (2 * n + d) // (2 * d)  # floor(x + 1/2) on a non-negative rational
    result = Decimal(q).scaleb(-places)
    if negative:
        result = -result
    return result.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def round_half_up_cents(value):
    """Integer cents produced by rounding half up (PRD §2.7)."""
    return int(round_half_up(value, 0))


def sqrt_decimal(value):
    """High-precision square root of a non-negative rational, as a Fraction."""
    frac = F(value)
    with localcontext() as ctx:
        ctx.prec = 60
        d = Decimal(frac.numerator) / Decimal(frac.denominator)
        return F(d.sqrt())


def num(value):
    """Render a Decimal / Fraction as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Fraction):
        return float(value)
    return value


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------

def serialize(row):
    """Strip private bookkeeping keys (prefixed with ``_``) from a stored row."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_many(rows):
    return [serialize(r) for r in rows]


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq", 0))


def sorted_rows(rows, descending=False):
    """List order per PRD §2.3: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=sort_key, reverse=descending)
