"""ISO 8601 UTC timestamp parsing and formatting.

All timestamps emitted by the API are ISO 8601 UTC with three fractional
digits and a Z suffix (PRD 2.6). Parsing tolerates optional fractional
digits and numeric offsets.
"""

import re
from datetime import datetime, timedelta, timezone

_DT_RE = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,6}))?\s*(Z|[+-]\d{2}:?\d{2})?\s*$"
)


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value)
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    micro = int((frac or "0").ljust(6, "0"))
    if tz is None or tz == "Z":
        offset = timezone.utc
    else:
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        offset = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    try:
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            microsecond=micro, tzinfo=offset,
        )
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_opt(dt):
    return fmt_dt(dt) if dt is not None else None
