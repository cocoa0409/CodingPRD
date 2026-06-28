"""In-memory data store. Wiped on every fresh boot (no persistence).

Each entity collection is a dict keyed by id. Insertion order is preserved by
Python dict semantics, which we rely on for created_at-ascending list ordering.

NOTE: NOTHING is seeded here. Every entity is created by tests through the
declared API surface.
"""
import uuid

from clock import clock


def iso(dt):
    """ISO 8601 UTC with three fractional digits and a Z suffix."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.plans = {}
        self.members = {}
        self.memberships = {}
        self.tanks = {}
        self.sanitation_cycles = {}
        self.attendants = {}
        self.orientations = {}
        self.bookings = {}
        self.gift_cards = {}
        self.credit_ledger = {}
        self.payments = {}
        # Monotonic sequence so append-only ledgers preserve a stable created
        # ordering even when many rows are written in the same logical instant.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def stamp_create(record):
    """Apply common system fields for a primary (versioned) record."""
    now = clock.now()
    rid = new_id()
    record["id"] = rid
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_ledger(record):
    """Apply common fields for an append-only ledger record (id + created_at)."""
    now = clock.now()
    record["id"] = new_id()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Bump updated_at + version on a primary record mutation."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1
    return record
