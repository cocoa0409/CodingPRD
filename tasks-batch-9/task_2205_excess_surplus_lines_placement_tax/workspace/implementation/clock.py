"""The server-held logical clock (PRD 2.4).

Every time-dependent rule reads this clock, never the host wall clock.
A freshly started process holds the clock at 2026-08-01T00:00:00Z.
"""

import re
from datetime import datetime, timedelta, timezone

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
DEFAULT_RAW = "2026-08-01T00:00:00.000Z"

_state = {"now": DEFAULT_INSTANT, "raw": DEFAULT_RAW}

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzpart = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro,
                        tzinfo=timezone.utc)
    except ValueError:
        return None
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        body = tzpart[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


def now():
    return _state["now"]


def now_iso():
    return fmt(_state["now"])


def now_raw():
    return _state["raw"]


def set_now(instant, raw=None):
    _state["now"] = instant
    _state["raw"] = raw if raw is not None else fmt(instant)


def reset():
    _state["now"] = DEFAULT_INSTANT
    _state["raw"] = DEFAULT_RAW
