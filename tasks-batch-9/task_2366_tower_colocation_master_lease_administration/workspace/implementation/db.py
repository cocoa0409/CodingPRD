"""In-memory store.

Nothing is ever seeded here: every collection starts empty on a cold boot and
every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Cold-start logical clock, fixed by PRD 2.4.  Never falls back to wall time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "towers",
    "landlords",
    "ground_leases",
    "landlord_payments",
    "tenants",
    "mlas",
    "applications",
    "equipment_lines",
    "analyses",
    "amendments",
    "projects",
    "cost_shares",
    "audits",
    "findings",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_record(**fields):
    """Create a record carrying id / created_at / updated_at / version."""
    record = {
        "id": new_id(),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
        "_seq": db.next_seq(),
    }
    record.update(fields)
    return record


def new_immutable_record(**fields):
    """Create a record carrying only id / created_at (LandlordPayment)."""
    record = {
        "id": new_id(),
        "created_at": db.clock,
        "_seq": db.next_seq(),
    }
    record.update(fields)
    return record


def bump(record):
    """A mutation (including a derived-field recomputation) on one record."""
    record["updated_at"] = db.clock
    record["version"] = record.get("version", 1) + 1
    return record


def order_key(record):
    return (record["created_at"], record["_seq"])


def sorted_records(records):
    return sorted(records, key=order_key)
