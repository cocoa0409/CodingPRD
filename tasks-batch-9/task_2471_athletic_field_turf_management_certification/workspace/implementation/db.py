"""In-memory data store.

Storage is process memory only and starts completely empty on every boot: no
seeding, no preloading, no fixtures.  Every entity is created by an API call.
"""

import itertools
import uuid

from timeutil import Instant

# PRD 2.4: before the clock has ever been set it reads exactly this instant and
# never falls back to real wall-clock time.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.fields = {}
        self.staff_members = {}
        self.maintenance_tasks = {}
        self.safety_assessments = {}
        self.remediation_orders = {}
        self.usage_bookings = {}
        self.ledger_entries = {}
        self.certification_packets = {}
        self.capital_budgets = {}
        self.replacement_plans = {}
        self.clock = Instant.from_input(CLOCK_EPOCH)
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """The logical clock (PRD 2.4)."""
    return db.clock


def common_fields():
    """created_at / updated_at / version for the nine versioned resource kinds."""
    stamp = Instant.now()
    return {"created_at": stamp, "updated_at": stamp, "version": 1, "_seq": db.next_seq()}


def bump(entity):
    """PRD 2.4: version increases by exactly 1 on every mutation of a resource."""
    entity["version"] = entity["version"] + 1
    entity["updated_at"] = Instant.now()


def by_creation(rows):
    return sorted(rows, key=lambda r: (r["created_at"].dt, r["_seq"]))
