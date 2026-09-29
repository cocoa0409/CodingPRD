"""Shared low-level helpers: datetime parsing/formatting and decimal rounding.

PRD 2.5: all datetimes are ISO 8601 UTC with three fractional digits.
PRD 2.7: all rounding in this system is round half up.
"""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 datetime. Returns None when malformed."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not _ISO_RE.match(s):
        return None
    s = s.replace(" ", "T").replace("t", "T")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt):
    """Format as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def dec(value):
    """Coerce to Decimal without float artefacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def money(value):
    """Serialize a 2-decimal monetary amount."""
    if value is None:
        return None
    return float(rhu(value, 2))


def ratio(value):
    """Serialize a 4-decimal ratio/score."""
    if value is None:
        return None
    return float(rhu(value, 4))


def floor_days(delta):
    """Whole days in a timedelta, discarding any partial day."""
    return int(delta.total_seconds() // 86400)


def floor_minutes(delta):
    """Whole minutes in a timedelta, discarding any partial minute."""
    return int(delta.total_seconds() // 60)


def dedup(seq):
    """Order-preserving de-duplication."""
    seen = set()
    out = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


DAY = timedelta(days=1)
MINUTE = timedelta(minutes=1)
