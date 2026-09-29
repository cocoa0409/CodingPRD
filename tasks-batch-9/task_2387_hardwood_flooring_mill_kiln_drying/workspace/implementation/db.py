"""In-memory data store.

Storage is pure Python dicts. Nothing is seeded, preloaded or hardcoded: every
collection below starts empty on every boot and is only ever populated through
the declared API surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# The logical clock default, per PRD section 2.4.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()

COLLECTION_NAMES = (
    "species_profiles",
    "drying_schedules",
    "green_receipts",
    "kiln_chambers",
    "kiln_charges",
    "product_lines",
    "core_stocks",
    "flooring_lots",
    "grade_runs",
    "grade_bundles",
    "prefinish_lines",
    "prefinish_runs",
    "byproduct_batches",
    "byproduct_sales",
    "warranty_claims",
)


class Store:
    def __init__(self):
        for name in COLLECTION_NAMES:
            setattr(self, name, {})
        self.current_utc = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    """Canonical UUID form, no type prefix of any kind (PRD 2.4)."""
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_iso():
    return iso(datetime.now(timezone.utc))


def logical_now():
    return db.current_utc


def logical_date():
    return db.current_utc.date()


def insert(collection, record, common_fields=True):
    """Create a record with server-minted identity / revision fields."""
    record["id"] = new_id()
    stamp = now_iso()
    record["created_at"] = stamp
    if common_fields:
        record["updated_at"] = stamp
        record["version"] = 1
    record["_seq"] = db.next_seq()
    collection[record["id"]] = record
    return record


def touch(record):
    """Bump the revision counter and refresh updated_at (PRD 2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = int(record.get("version", 0)) + 1
    return record


def ordered(collection):
    """Ascending created_at order -- oldest first (PRD 2.3)."""
    return sorted(collection.values(), key=lambda r: r["_seq"])
