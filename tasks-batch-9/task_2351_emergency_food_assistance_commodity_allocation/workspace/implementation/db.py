"""In-memory data store and the logical program clock (PRD §2.4, §2.5).

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every row a test needs is created through the declared API surface.
"""

import uuid
from datetime import datetime, timezone

# PRD §2.4 — the clock starts at this fixed instant and never falls back to
# wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.service_areas = {}
        self.agencies = {}
        self.commodities = {}
        self.warehouses = {}
        self.lots = {}
        self.cycles = {}
        self.allocations = {}
        self.orders = {}
        self.order_lines = {}
        self.appointments = {}
        self.transfers = {}
        self.recalls = {}
        self.recall_actions = {}
        self.distributions = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current instant, per the logical program clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_row(versioned=True):
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version (PRD §2.5)."""
    if row is None:
        return row
    row["updated_at"] = now()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def ordered(rows):
    """Default list order: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
