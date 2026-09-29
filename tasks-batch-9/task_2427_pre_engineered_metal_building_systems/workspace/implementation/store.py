"""In-memory data store, id minting, timestamps and the logical clock.

The store starts EMPTY on every boot. Nothing here seeds, preloads or hardcodes
any entity: every row is created by a client through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: at server startup the logical clock reads exactly this instant and
# never falls back to real wall-clock time.
LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class Store(object):
    def __init__(self):
        self.jurisdictions = {}
        self.builders = {}
        self.configurations = {}
        self.accessory_kits = {}
        self.quotes = {}
        self.designs = {}
        self.components = {}
        self.drawing_packages = {}
        self.orders = {}
        self.production_lines = {}
        self.production_lots = {}
        self.shipment_loads = {}
        self.logical_clock = LOGICAL_CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --- time helpers ---------------------------------------------------------
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    """created_at / updated_at stamps.

    PRD 2.4: "Time in this system is a logical clock, not wall-clock time. At
    server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it
    never falls back to real time."  Every resource timestamp -- including the
    audit stamps -- therefore reads the logical clock.
    """
    return fmt_dt(db.logical_clock)


def now():
    """Current logical clock instant."""
    return db.logical_clock


def now_iso():
    return fmt_dt(db.logical_clock)


def set_clock(dt):
    db.logical_clock = dt.astimezone(timezone.utc)
    return db.logical_clock


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --- row helpers ---------------------------------------------------------
def new_row(fields, versioned=True):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": wall_now(),
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = wall_now()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(table, predicate=None):
    """All rows of a table in created_at ascending (insertion) order."""
    rows = [r for r in table.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: r["_seq"])
    return rows
