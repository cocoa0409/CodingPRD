"""In-memory data store and the server-held logical clock.

The store starts completely empty on every boot. The logical clock defaults to
exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""
import threading
from datetime import datetime, timezone

LOCK = threading.RLock()

STORE = {
    "modules": {},
    "coaches": {},
    "participants": {},
    "workshops": {},
    "registrations": {},
    "cases": {},
    "goal_plans": {},
    "snapshots": {},
    "pools": {},
    "enrollments": {},
    "referrals": {},
    "reports": {},
}

_seq = [0]


def next_seq():
    """Monotonic insertion sequence used as a stable tie-break for ordering."""
    _seq[0] += 1
    return _seq[0]


_clock = [datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)]


def logical_now():
    return _clock[0]


def set_logical_clock(dt):
    _clock[0] = dt
