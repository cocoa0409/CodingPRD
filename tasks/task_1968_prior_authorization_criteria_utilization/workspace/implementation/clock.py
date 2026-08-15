"""Server-managed logical clock.

The platform never trusts wall-clock time. The clock starts at exactly
2026-08-01T00:00:00Z and only moves when POST /um/_clock/set_current_utc
is called.
"""

import re
from datetime import datetime, timedelta, timezone

START_OF_TIME = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = START_OF_TIME


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return _now


def set_now(dt):
    global _now
    _now = dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def parse(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a well-formed datetime string.
    Naive inputs are interpreted as UTC.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    if tzs is None or tzs == "Z":
        tz = timezone.utc
    else:
        sign = 1 if tzs[0] == "+" else -1
        digits = tzs[1:].replace(":", "")
        off_h, off_m = int(digits[:2]), int(digits[2:4])
        tz = timezone(sign * timedelta(hours=off_h, minutes=off_m))
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)
