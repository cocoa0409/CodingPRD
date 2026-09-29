"""The logical clock (PRD section 2.5).

Nothing in this system reads real wall-clock time.  On startup the clock stands
at exactly 2026-08-01T00:00:00Z and it stays there until an administrator moves
it through POST /_clock/set_current_utc.
"""

import re
from datetime import datetime, timedelta, timezone

STARTUP_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": STARTUP_INSTANT}

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def now():
    """Current value of the logical clock."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = STARTUP_INSTANT


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse(value):
    """Parse an RFC3339 UTC timestamp.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = _ISO_RE.match(text)
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        off_hours = int(body[:2])
        off_minutes = int(body[2:4])
        base = base - sign * timedelta(hours=off_hours, minutes=off_minutes)
    return base


def plus_days(dt, days):
    return dt + timedelta(days=days)
