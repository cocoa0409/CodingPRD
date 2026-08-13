"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seed data of any kind.
The logical clock defaults to exactly 2026-08-01T00:00:00Z and is only ever
moved by POST /_clock/set_current_utc; it never falls back to wall-clock time.
"""
import itertools
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.locals = {}
        self.classifications = {}
        self.employers = {}
        self.members = {}
        self.assessments = {}          # assessment_id -> dict
        self.ledger_entries = {}       # entry_id -> dict
        self.remittances = {}
        self.remittance_lines = {}     # line_id -> dict
        self.notices = {}
        self.objector_cases = {}
        self.transfers = {}
        self.per_capita_reports = {}
        self.elections = {}
        self.eligibilities = {}
        self.assessment_runs = {}
        # Monotonic insertion sequence: created_at ties are broken by insertion
        # order (created_at is non-decreasing with insertion).
        self.seq = itertools.count(1)
        # Logical clock; startup default exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.RLock()

    def next_seq(self):
        return next(self.seq)


store = Store()


def now():
    """Current logical-clock instant (aware, UTC)."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def current_period():
    c = store.clock
    return "%04d-%02d" % (c.year, c.month)


def touch(entity, bump_version=True):
    """Refresh updated_at (and bump version) on a mutable resource."""
    entity["updated_at"] = fmt_ts(now())
    if bump_version:
        entity["version"] = entity.get("version", 1) + 1


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
