"""In-memory data store.

Every collection is a plain dict keyed by the entity's server-minted UUID.
The store starts EMPTY on every process boot — nothing is seeded or preloaded.
Tests build all preconditions through the declared API surface.
"""

import itertools
import uuid

from response import now_iso

# Per-process monotonic sequence so insertion order (and thus created_at tie
# breaking by creation) is total and deterministic even within the same
# millisecond.
_seq = itertools.count(1)


class Store:
    def __init__(self):
        self.students = {}
        self.instructors = {}
        self.aircraft = {}
        self.syllabi = {}
        self.enrollments = {}
        self.deposit_transactions = {}
        self.squawks = {}
        self.bookings = {}
        self.flight_logs = {}
        self.stage_checks = {}
        self.endorsements = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def new_common():
    """System-managed fields for a versioned, mutable entity."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_lean():
    """System-managed fields for a lean, append-only/immutable entity
    (Syllabus, DepositTransaction): id + created_at only."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }


def touch(record):
    """Record a mutation on a versioned entity: bump version + updated_at."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def public(record):
    """Strip internal bookkeeping fields before serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def sorted_by_created(records):
    """Sort by created_at ascending; tie-break by insertion sequence."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
