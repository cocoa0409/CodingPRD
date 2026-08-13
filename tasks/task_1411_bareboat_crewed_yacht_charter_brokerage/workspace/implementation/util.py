"""Utility helpers: timestamps, calendar dates, decimal money math.

All monetary math uses Decimal with ROUND_HALF_UP at each pinned rounding step
(PRD §2.6). Dates are YYYY-MM-DD strings; datetimes are aware UTC objects
internally and serialize as ISO 8601 with three fractional digits (PRD §2.4).
"""

import re
import uuid
from datetime import date as _date
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    if not _TS_RE.match(value.strip()):
        return None
    s = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Strictly validate a YYYY-MM-DD calendar date; return normalized string."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not _DATE_RE.match(s):
        return None
    try:
        d = _date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        return None
    return d.isoformat()


def date_obj(date_str):
    """Normalized YYYY-MM-DD string -> datetime.date."""
    return _date.fromisoformat(date_str)


def wall_now_ts():
    """Wall-clock UTC timestamp (used only for the meta envelope block)."""
    return fmt_ts(datetime.now(timezone.utc))


def new_uuid():
    return str(uuid.uuid4())


def round_cents(value):
    """Round a Decimal-compatible value half-up to whole integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    """Exact Decimal from an int/float/str without binary float artifacts."""
    return Decimal(str(value))
