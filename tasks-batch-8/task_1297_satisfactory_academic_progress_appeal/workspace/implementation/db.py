"""In-memory data store and the single logical clock.

The store starts completely empty on every boot — no seeding of any kind.
Every entity any caller needs is constructed through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone


def _new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.programs = {}
        self.students = {}
        self.terms = {}
        self.enrollments = {}
        self.evaluations = {}
        self.appeals = {}
        self.plans = {}
        self.checkpoints = {}
        self.notifications = {}
        self.audit_events = {}
        # Monotonic insertion counter — deterministic ordering tiebreak for
        # rows that share a logical-clock created_at. Never serialized.
        self.seq = 0
        # The single logical clock. Server startup default is exactly
        # 2026-08-01T00:00:00Z; the wall clock is never read.
        self.current_utc = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.RLock()

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    """Current logical time (timezone-aware UTC)."""
    return store.current_utc


def set_now(target):
    store.current_utc = target


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------
# Logical-clock timestamps (evaluated_at, submitted_at, decided_at,
# occurred_at, scheduled_at, sent_at, appeal_deadline_at, current_utc) use
# second precision: "2026-08-01T00:00:00Z".
def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if dt.microsecond % 1000 == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%06dZ" % dt.microsecond


# created_at / updated_at / api_request_timestamp carry three fractional
# digits: "2026-08-01T00:00:00.000Z".
def fmt_common(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def trunc_second(dt):
    return dt.replace(microsecond=0)
