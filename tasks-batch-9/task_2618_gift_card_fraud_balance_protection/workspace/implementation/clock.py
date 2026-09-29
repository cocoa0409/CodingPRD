"""Deterministic logical clock (PRD 2.4)."""
import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
EPOCH_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_state = {"now": EPOCH_START}

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = EPOCH_START


def fmt(dt):
    """ISO-8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    d = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000,
    )


def parse(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None when invalid."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    off = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * delta
    return base
