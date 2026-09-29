"""In-memory data store and the logical clock (PRD Section 2.5).

Nothing is seeded here: the store starts empty on every boot and all state is
built through the declared endpoints.
"""

import itertools
import uuid
from datetime import datetime, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.buildings = {}
        self.suites = {}
        self.tenants = {}
        self.leases = {}
        self.appraisals = {}
        self.ti_projects = {}
        self.ti_line_items = {}
        self.rent_invoices = {}
        self.compliance_cases = {}
        self.shared_spaces = {}
        self.bookings = {}
        self.parking_allocations = {}
        self.clock = CLOCK_EPOCH
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_instant(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_instant():
    """created_at / updated_at come from the logical clock: the service never
    reads wall-clock time for row state (PRD Section 2.5)."""
    return fmt_instant(db.clock)


def clock_date():
    return db.clock.date()


def stamp_new(row, versioned=True):
    row["id"] = new_id()
    row["created_at"] = now_instant()
    if versioned:
        row["updated_at"] = now_instant()
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    row["updated_at"] = now_instant()
    row["version"] = row.get("version", 1) + 1
    return row


def by_creation(rows):
    """Default list order: created_at ascending (insertion order is the
    tie-break, since the logical clock is monotonic)."""
    return sorted(rows, key=lambda r: r["_seq"])
