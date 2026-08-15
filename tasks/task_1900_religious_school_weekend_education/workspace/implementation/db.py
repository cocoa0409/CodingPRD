"""In-memory data store and logical clock.

The store starts empty on every boot — no seeding of any kind.
"""

import uuid
import threading
from datetime import datetime, timezone


class Clock:
    """Logical clock. Default at startup is exactly 2026-08-01T00:00:00Z."""

    def __init__(self):
        self._lock = threading.Lock()
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        with self._lock:
            return self._now

    def set(self, dt):
        with self._lock:
            self._now = dt
        return self._now


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.clock = Clock()
        # entity stores, keyed by id
        self.school_years = {}
        self.security_plans = {}
        self.closures = {}
        self.families = {}
        self.students = {}
        self.teachers = {}
        self.sections = {}
        self.enrollments = {}
        self.invoices = {}
        self.payments = {}
        self.applications = {}
        self.sessions = {}
        self.milestones = {}
        self.commitments = {}
        # request-arrival counter to break created_at ties deterministically
        self._seq_lock = threading.Lock()
        self._seq = 0

    def next_seq(self):
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def now(self):
        return self.clock.now()

    def now_str(self):
        return fmt_ts(self.clock.now())


store = Store()
