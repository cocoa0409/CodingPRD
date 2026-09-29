"""In-memory data store and the logical clock.

Every collection starts EMPTY on every boot; nothing is seeded, preloaded or
hardcoded.  Tests build all state through the declared endpoints.
"""

import itertools
import uuid
from datetime import datetime, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prescribers = {}
        self.prescriptions = {}
        self.patients = {}
        self.insurance_plans = {}
        self.lens_designs = {}
        self.tolerance_standards = {}
        self.lens_blank_lots = {}
        self.rx_orders = {}
        self.frame_layouts = {}
        self.lab_jobs = {}
        self.lab_machines = {}
        self.finishing_bays = {}
        self.lab_operations = {}
        self.quality_inspections = {}
        self.remake_cases = {}
        self.settlement_entries = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """The logical clock instant."""
    return db.clock


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def stamp_common(row):
    """Attach the common fields to a freshly created versioned row."""
    row["id"] = new_id()
    row["created_at"] = now()
    row["updated_at"] = now()
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def stamp_event(row):
    """Attach the common fields to a freshly created append-only event row."""
    row["id"] = new_id()
    row["created_at"] = now()
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """A persisted write to a versioned row: bump version, refresh updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now()
    return row


def sorted_rows(collection, reverse=False):
    return sorted(collection.values(), key=lambda r: r["_seq"], reverse=reverse)
