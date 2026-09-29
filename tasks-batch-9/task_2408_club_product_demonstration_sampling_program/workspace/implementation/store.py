"""In-memory data store, logical clock and system-field primitives.

Storage is process-local and starts completely empty on every boot: no seeding,
no preloading, no persistence to disk.
"""

import uuid
from datetime import datetime, timezone

# PRD 2.5: until an operator sets it, the logical clock reads exactly this
# instant and must never fall back to real wall-clock time.
DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK_UTC
        self._seq = 0
        self.manufacturers = {}
        self.clubs = {}
        self.products = {}
        self.baselines = {}
        self.demo_events = {}
        self.demonstrators = {}
        self.certifications = {}
        self.assignments = {}
        self.equipment_units = {}
        self.reservations = {}
        self.shipments = {}
        self.reconciliations = {}
        self.measurements = {}
        self.invoices = {}
        self.credits = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return db.clock


def today():
    """Current logical-clock UTC calendar date."""
    return db.clock.date()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def iso_now():
    return iso(now())


def new_id():
    return str(uuid.uuid4())


def new_row(**fields):
    """Row carrying the four common system fields of PRD 2.4."""
    stamp = iso_now()
    row = {"id": new_id(), "created_at": stamp, "updated_at": stamp, "version": 1}
    row.update(fields)
    row["_seq"] = db.next_seq()
    return row


def new_ledger_row(**fields):
    """Row for the append-only measurement ledger: id + created_at only."""
    row = {"id": new_id(), "created_at": iso_now()}
    row.update(fields)
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """A mutation of a row refreshes updated_at and increments version by 1."""
    row["updated_at"] = iso_now()
    row["version"] = row.get("version", 1) + 1


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
