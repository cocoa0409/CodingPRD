"""Shared helpers: decimal precision, timestamps, date/datetime parsing."""
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

Q3 = Decimal("0.001")
Q2 = Decimal("0.01")
Q0 = Decimal("1")
D0 = Decimal("0")


def round3(d):
    return Decimal(d).quantize(Q3, rounding=ROUND_HALF_UP)


def round2(d):
    return Decimal(d).quantize(Q2, rounding=ROUND_HALF_UP)


def round_cents(d):
    """Round half-up to integer cents, returned as int."""
    return int(Decimal(d).quantize(Q0, rounding=ROUND_HALF_UP))


def iso_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_datetime(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_ymd(s):
    """Strictly parse a YYYY-MM-DD date string, or None."""
    if not isinstance(s, str):
        return None
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def to_decimal(x):
    """Convert a JSON number to Decimal; None when not a number."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return Decimal(str(x))
    return None


def dp_ok(d, places):
    """True when the Decimal carries no more than `places` decimal places."""
    return -d.as_tuple().exponent <= places


def num_out(d):
    """Serialize a Decimal acre-feet / depth value as a JSON number."""
    return float(d)
