"""Logical clock (PRD 2.4) plus real-time record timestamps."""
import threading
from datetime import datetime, timezone, timedelta

# PRD 2.4: before any client sets it the logical clock reads exactly
# 2026-08-01T00:00:00Z and it never falls back to real wall-clock time.
_LOGICAL_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"logical": _LOGICAL_DEFAULT, "last_real": None}
_lock = threading.Lock()


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def set_logical(dt):
    _state["logical"] = dt.astimezone(timezone.utc)


def logical_now():
    return _state["logical"]


def logical_iso():
    return fmt(_state["logical"])


def logical_date():
    """Date portion of the logical clock, as a YYYY-MM-DD string."""
    return _state["logical"].strftime("%Y-%m-%d")


def real_now_iso():
    """Strictly increasing millisecond-resolution wall-clock stamp."""
    now = datetime.now(timezone.utc)
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    with _lock:
        last = _state["last_real"]
        if last is not None and now <= last:
            now = last + timedelta(milliseconds=1)
        _state["last_real"] = now
    return fmt(now)
