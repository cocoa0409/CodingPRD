"""In-memory data store and the server's logical clock.

The store is EMPTY on every boot - nothing is seeded, preloaded or hardcoded.
Every row is created by a client through a declared endpoint.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# PRD 2.4: the logical clock starts at exactly 2026-08-01T00:00:00Z and never
# falls back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "venues", "distributors", "titles", "bookings", "offers", "clearances",
    "assets", "keys", "showtimes", "events", "orders", "members", "settlements",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical clock instant."""
    return db.clock


def set_clock(instant):
    db.clock = instant


def new_id():
    return str(uuid.uuid4())


def new_record(**fields):
    """Mint a row with the four common properties (PRD 2.4)."""
    rec = {
        "id": new_id(),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1 (direct or cascade)."""
    rec["updated_at"] = db.clock
    rec["version"] = rec["version"] + 1
    return rec


def ordered(rows):
    """PRD 2.3: list results are ordered by created_at ascending."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def rows_of(collection):
    """All rows of a collection in insertion-independent list form."""
    return list(getattr(db, collection).values())
