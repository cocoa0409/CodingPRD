"""The single logical clock (PRD §2.5). Wall clock is never consulted.

Startup default reads exactly 2026-05-01T00:00:00Z. All domain timestamps
(created_at, updated_at, submitted_at, filed_at, issued_at, actual_*_on) and
the envelope's api_request_timestamp are stamped from this clock.
"""
import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()
_DEFAULT = "2026-05-01T00:00:00Z"


def _parse_iso(value):
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


_now = _parse_iso(_DEFAULT)


def now():
    with _LOCK:
        return _now


def set_now(value):
    global _now
    dt = _parse_iso(value)
    with _LOCK:
        _now = dt
    return dt


def today():
    return now().date()
