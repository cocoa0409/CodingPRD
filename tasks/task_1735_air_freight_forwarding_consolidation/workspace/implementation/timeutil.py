"""ISO-8601 parsing/formatting.

All timestamps on the wire are ISO 8601 UTC with exactly three fractional
digits, e.g. 2026-08-01T00:00:00.000Z (PRD §2.2/§2.4).
"""
import re
from datetime import datetime, timedelta, timezone

_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"(?:[T ](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:\.(?P<f>\d{1,9}))?)?)?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not an ISO-8601 string")
    s = value.strip()
    m = _ISO_RE.match(s)
    if not m:
        raise ValueError("not an ISO-8601 string")
    try:
        year = int(m.group("y"))
        month = int(m.group("mo"))
        day = int(m.group("d"))
        hour = int(m.group("h") or 0)
        minute = int(m.group("mi") or 0)
        second = int(m.group("s") or 0)
        frac = m.group("f") or ""
        micro = int((frac + "000000")[:6]) if frac else 0
        tzs = m.group("tz")
        if tzs is None or tzs in ("Z", "z"):
            tz = timezone.utc
        else:
            sign = 1 if tzs[0] == "+" else -1
            digits = tzs[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4])))
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    except ValueError:
        raise ValueError("not an ISO-8601 string")
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
