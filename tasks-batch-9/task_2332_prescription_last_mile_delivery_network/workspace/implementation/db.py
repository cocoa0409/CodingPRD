"""In-memory data store for the ScriptDrop prescription last-mile delivery API.

Storage is process-local Python dictionaries only. The store is EMPTY on every
boot: nothing is seeded, preloaded or hardcoded. Every entity is created through
the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# The logical clock defaults here and stays until POST /_clock/set_current_utc.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_real():
    """Wall-clock UTC instant, used for created_at / updated_at bookkeeping."""
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.health_plans = {}
        self.plan_grants = {}
        self.pharmacies = {}
        self.patients = {}
        self.delivery_zones = {}
        self.delivery_windows = {}
        self.pharmacy_orders = {}
        self.couriers = {}
        self.deliveries = {}
        self.courier_assignments = {}
        self.delivery_attempts = {}
        self.fee_allocations = {}
        self.exception_cases = {}
        self.disclosures = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_row(versioned=True):
    """Mint a row with its system-managed identity / timestamp / version fields."""
    stamp = iso(now_real())
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version — one mutation of one row."""
    if row is None:
        return
    row["updated_at"] = iso(now_real())
    row["version"] = row.get("version", 0) + 1


def sort_rows(rows):
    """Default ordering for every list endpoint: created_at ascending."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
