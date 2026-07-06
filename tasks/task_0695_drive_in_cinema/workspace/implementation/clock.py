"""The logical clock (PRD §2.8).

At startup the clock reads exactly 2026-03-01T00:00:00Z, and until it is
explicitly set it never falls back to real time.
"""
from datetime import datetime, timezone

# Module-level state — reset to default on every fresh process boot, which is
# exactly what the per-test-server harness wants.
_now = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt
