"""In-memory data store for the Solar Reroof Coordination API.

Storage is process-local Python dictionaries only. The store starts completely
empty on every boot: no entity is ever seeded, preloaded or hardcoded.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any clock-setting call the logical clock reads exactly this
# instant, and it never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.parties = {}
        self.jurisdictions = {}
        self.projects = {}
        self.approvals = {}
        self.circuits = {}
        self.bins = {}
        self.units = {}
        self.findings = {}
        self.permits = {}
        self.inspections = {}
        self.windows = {}
        self.orders = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(fields, common=True):
    """Create a persisted row carrying the system-managed common fields."""
    now = db.now()
    row = {"id": new_id(), "created_at": now}
    if common:
        row["updated_at"] = now
        row["version"] = 1
    row.update(fields)
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Register a mutation of a row: refresh updated_at and bump version."""
    row["updated_at"] = db.now()
    row["version"] = row.get("version", 1) + 1


def ordered(rows):
    """Default list ordering: created_at ascending (stable by insertion)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
