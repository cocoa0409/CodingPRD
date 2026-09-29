"""Logical clock (PRD 2.4).

Nothing in this system reads the host wall clock.  The logical clock starts at
exactly 2026-08-01T00:00:00Z on every fresh process and only moves when a
ComplianceAdmin calls POST /_clock/set_current_utc.
"""

import re
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def reset():
    _state["now"] = DEFAULT_NOW


_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"[Tt ](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:\.(?P<f>\d+))?)?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    frac = m.group("f") or ""
    frac = (frac + "000000")[:6]
    try:
        base = datetime(
            int(m.group("y")),
            int(m.group("mo")),
            int(m.group("d")),
            int(m.group("h")),
            int(m.group("mi")),
            int(m.group("s") or 0),
            int(frac),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    tz = m.group("tz")
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz_body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz_body[:2]), minutes=int(tz_body[2:4]))
        base = base - sign * offset
    return base


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def whole_seconds(dt):
    """Whole-second granularity comparison key (PRD 2.6 / 3.5)."""
    return int(dt.timestamp())
