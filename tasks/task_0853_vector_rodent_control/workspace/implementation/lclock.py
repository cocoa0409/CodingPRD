"""The program logical clock and the single shared timestamp renderer.

PRD 2.4: time is NEVER read from wall-clock. The clock reads exactly
2026-05-01T00:00:00Z at start-up and moves only when a ProgramAdmin drives it.
All timestamps in requests and responses are ISO 8601 UTC strings rendered with
exactly three fractional-second digits, e.g. 2026-05-01T00:00:00.000Z.

Every server-generated timestamp in this codebase MUST be produced by render()
below; there is no other formatting path.
"""

import datetime
import re

UTC = datetime.timezone.utc

DEFAULT_CLOCK = datetime.datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)

_state = {"now": DEFAULT_CLOCK}


def now():
    """Current logical-clock instant (timezone-aware, UTC)."""
    return _state["now"]


def set_now(dt):
    """Move the logical clock. Returns the previous instant."""
    previous = _state["now"]
    _state["now"] = dt.astimezone(UTC)
    return previous


def reset():
    _state["now"] = DEFAULT_CLOCK


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ]"
    r"(\d{2}):(\d{2})"
    r"(?::(\d{2}))?"
    r"(?:[.,](\d{1,9}))?"
    r"\s*(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Raises ValueError when the value is not a well-formed instant. A missing
    offset is treated as UTC.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    m = _ISO_RE.match(value.strip())
    if not m:
        raise ValueError("malformed ISO 8601 timestamp: %r" % (value,))
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime.datetime(year, month, day, hour, minute, second, micro)
    except ValueError as exc:
        raise ValueError(str(exc))
    if offset in (None, "Z", "z"):
        return dt.replace(tzinfo=UTC)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta = datetime.timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (dt - sign * delta).replace(tzinfo=UTC)


def render(dt):
    """The ONE renderer: ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def plus_days(dt, days):
    return dt + datetime.timedelta(days=days)


def plus_hours(dt, hours):
    return dt + datetime.timedelta(hours=hours)
