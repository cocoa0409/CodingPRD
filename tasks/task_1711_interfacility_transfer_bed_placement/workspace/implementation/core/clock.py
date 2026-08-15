"""The logical clock of PRD section 2.4.

Nothing in this implementation reads the machine's wall clock.  The logical
clock starts at exactly 2026-08-01T00:00:00Z and moves only through
POST /_clock/set_current_utc.  All system timestamps, expiries, SLAs,
diversion windows and computed durations read this clock.

Instants are stored internally as naive UTC datetimes; the server-written
rendering is always YYYY-MM-DDTHH:MM:SS.mmmZ (three fractional digits).
"""

import re
from datetime import datetime, timedelta

_ISO_INSTANT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0)


def parse_instant(text):
    """Parse an ISO 8601 instant into a naive UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    m = _ISO_INSTANT.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def render_instant(dt):
    """Server-written instant: YYYY-MM-DDTHH:MM:SS.mmmZ, three digits always."""
    if dt is None:
        return None
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def floor_minutes_between(start, end):
    """floor((end - start) in seconds / 60): the realized-duration convention."""
    return int((end - start).total_seconds()) // 60
