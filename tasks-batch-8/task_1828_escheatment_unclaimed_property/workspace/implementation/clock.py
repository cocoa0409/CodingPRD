"""Logical clock per PRD section 2.5.

The server never consults wall-clock time for business logic. The logical
clock starts at exactly 2026-08-01T00:00:00Z and is only moved via
POST /escheatment/_clock/set_current_utc. Stamps recorded into date fields
(sent_date, submitted_date, ...) use the logical clock's calendar date;
datetime stamps (created_at, updated_at, purged_at, meta timestamps) also
derive from the logical clock, advanced monotonically so repeated stamps
within one logical day remain distinct and non-decreasing.
"""

import threading
from datetime import datetime, timezone, timedelta

_LOCK = threading.Lock()
_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
# Monotonic microsecond offset used so consecutive stamps never go backwards
# even when the clock is set repeatedly to the same instant.
_seq_us = 0


def _format_z(dt):
    """Format a UTC datetime as ISO8601 with three fractional digits + Z."""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def set_current(dt):
    """Move the logical clock to the supplied aware UTC datetime."""
    global _current, _seq_us
    with _LOCK:
        _current = dt.astimezone(timezone.utc)
        _seq_us = 0


def now():
    """Current logical clock reading as an aware UTC datetime.

    Each call advances the reading by one millisecond if needed so that
    consecutive stamps within a request run are strictly increasing.
    """
    global _current, _seq_us
    with _LOCK:
        stamp = _current + timedelta(milliseconds=_seq_us)
        _seq_us += 1
        return stamp


def now_iso():
    """Current logical clock reading formatted with three fractional digits."""
    return _format_z(now())


def today():
    """The logical clock's calendar date (PRD 'the clock date')."""
    with _LOCK:
        return _current.date()


def current_utc_iso():
    """Clock reading without consuming a sequence tick (for clock responses)."""
    with _LOCK:
        return _format_z(_current)
