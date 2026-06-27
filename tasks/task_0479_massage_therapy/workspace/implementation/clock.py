"""Server-wide logical clock (PRD §2.5).

The server starts with the clock fixed at 2026-01-01T00:00:00Z. A PracticeAdmin
may set it to any explicit UTC instant; it may be advanced or rewound.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _DEFAULT


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def reset():
    global _now
    _now = _DEFAULT
