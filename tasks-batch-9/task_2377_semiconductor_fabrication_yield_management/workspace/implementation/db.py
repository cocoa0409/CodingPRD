"""In-memory data store.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded.  Every row is created through the declared API surface.
"""
import clock
from errors import fail
from util import new_id


class DB:
    def __init__(self):
        self.process_flows = {}
        self.process_steps = {}
        self.recipes = {}
        self.change_requests = {}
        self.equipment = {}
        self.chambers = {}
        self.operators = {}
        self.plans = {}
        self.lots = {}
        self.step_runs = {}
        self.spc_charts = {}
        self.measurements = {}
        self.excursions = {}
        self.die_sort_runs = {}


db = DB()


def new_row(fields, versioned=True):
    """Common resource properties (PRD 2.4)."""
    stamp = clock.now()
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def need(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id, "No such resource: %s" % row_id)
    return row


def ordered(rows):
    """Default list ordering: created_at ascending (stable on insertion order)."""
    return sorted(rows, key=lambda r: r["created_at"])
