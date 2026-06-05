"""In-memory data store and the test-driving clock.

Everything lives in plain Python dicts keyed by id. State is wiped on every
process start (per-test-server isolation re-launches the server before each
test). No seeding, no persistence.
"""
import threading
import uuid
from datetime import datetime, timezone


_lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + uuid.uuid4().hex[:20]


class Clock:
    """Server clock. Starts at real wall-clock UTC; tests may set/advance it."""

    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def set_to(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)

    def advance_days(self, days):
        from datetime import timedelta
        self._now = self._now + timedelta(days=days)


class Store:
    """Holds one dict per entity collection. Empty at boot."""

    COLLECTIONS = [
        "jurisdictions",
        "contractors",
        "permits",
        "plan_reviews",
        "correction_notices",
        "inspectors",
        "plan_reviewers",
        "inspection_slots",
        "inspections",
        "stop_work_orders",
        "certificates",
        "fee_payments",
        "permit_events",
    ]

    def __init__(self):
        self.clock = Clock()
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        # monotonic sequence to provide a stable secondary sort key so that
        # rows created within the same millisecond still order by insertion.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
lock = _lock


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_ts(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
