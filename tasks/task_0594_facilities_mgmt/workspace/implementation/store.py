"""In-memory data store and the logical clock.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here -- every entity is created through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: at server startup the logical clock reads exactly 2026-05-01T00:00:00Z.
CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.buildings = {}
        self.spaces = {}
        self.assets = {}
        self.pm_plans = {}
        self.vendors = {}
        self.work_orders = {}
        self.dispatches = {}
        self.shifts = {}
        self.readings = {}
        self.leases = {}
        self.allocations = {}
        self.statements = {}
        self.projects = {}
        self.clock = CLOCK_START
        self._seq = itertools.count(1)

    def seq(self):
        return next(self._seq)


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_fields(versioned=True):
    """Common fields (PRD 2.4).  UtilityReading passes versioned=False."""
    stamp = db.clock
    row = {"id": new_id(), "created_at": stamp, "_seq": db.seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = db.clock
    row["version"] = row.get("version", 1) + 1


def ordered(rows):
    """Default list ordering: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
