"""Date, money, and numeric helpers.

All money is integer cents. round-half-up means round half AWAY FROM ZERO.
Exact rational arithmetic uses fractions.Fraction so no float drift creeps in.
"""
import math
from datetime import datetime, timezone, timedelta
from fractions import Fraction


# ---------------------------------------------------------------------------
# Numeric / money
# ---------------------------------------------------------------------------
def to_fraction(x):
    """Convert an int/float/str/Fraction to an exact Fraction.

    Floats are routed through str() so 0.1 becomes Fraction(1, 10) rather than
    the binary-exact 3602879701896397/36028797018963968.
    """
    if isinstance(x, Fraction):
        return x
    if isinstance(x, bool):
        return Fraction(int(x))
    if isinstance(x, int):
        return Fraction(x)
    return Fraction(str(x))


def rhu(value):
    """Round half up (away from zero) a Fraction/number to a whole integer."""
    fr = value if isinstance(value, Fraction) else to_fraction(value)
    sign = 1 if fr >= 0 else -1
    fr = abs(fr)
    q, r = divmod(fr.numerator, fr.denominator)
    if 2 * r >= fr.denominator:
        q += 1
    return sign * q


def ffloor(value):
    fr = value if isinstance(value, Fraction) else to_fraction(value)
    return math.floor(fr)


# ---------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------
def parse_dt(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc) if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = datetime.fromisoformat(text + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_years(dt, k):
    year = dt.year + k
    try:
        return dt.replace(year=year)
    except ValueError:
        # Feb 29 -> Feb 28 on a non-leap target year
        return dt.replace(year=year, day=28)


def add_days(dt, k):
    return dt + timedelta(days=k)


def days_30_360(d1, d2):
    """US (NASD) 30/360 day count between two datetimes."""
    y1, m1, day1 = d1.year, d1.month, d1.day
    y2, m2, day2 = d2.year, d2.month, d2.day
    if day1 == 31:
        day1 = 30
    if day2 == 31 and day1 == 30:
        day2 = 30
    return 360 * (y2 - y1) + 30 * (m2 - m1) + (day2 - day1)
