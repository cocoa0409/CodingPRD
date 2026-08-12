"""In-memory store. Starts EMPTY on every boot -- nothing is ever seeded."""
import itertools
import random
import threading
import uuid

import clock

VERSIONED = {
    "catalog_items",
    "agency_forms",
    "consulates",
    "slots",
    "orders",
    "applicants",
    "documents",
    "photos",
    "prepared_forms",
    "appointments",
    "courier_legs",
    "rfes",
    "shipments",
}

APPEND_ONLY = {
    "document_requirements",
    "custody_events",
    "ledger_entries",
    "sla_segments",
}

COLLECTIONS = sorted(VERSIONED | APPEND_ONLY)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})


DB = Store()


_SEQ = itertools.count(1)
_SEQ_LOCK = threading.Lock()


def new_id():
    """A server-minted UUID string whose lexicographic order follows mint order.

    PRD 2.3 makes the `id` tie-break load-bearing precisely because the logical
    clock is coarse and many rows share a single `created_at`. A random UUID
    would make that tie-break arbitrary, so the high 48 bits carry a monotonic
    counter; the remaining bits are random and the UUID version/variant nibbles
    sit below the counter, so ordering is preserved.
    """
    with _SEQ_LOCK:
        seq = next(_SEQ)
    value = ((seq & ((1 << 48) - 1)) << 80) | random.getrandbits(80)
    return str(uuid.UUID(int=value, version=4))


def insert(collection, row):
    """Mint id/created_at (and updated_at/version for versioned rows) then store."""
    row["id"] = new_id()
    row["created_at"] = clock.now()
    if collection in VERSIONED:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    getattr(DB, collection)[row["id"]] = row
    return row


def touch(row):
    """Bump version by exactly 1 and stamp updated_at (PRD 2.10 general rule)."""
    if row is None:
        return row
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = clock.now()
    return row


def all_rows(collection):
    return list(getattr(DB, collection).values())


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(DB, collection).get(row_id)


def sort_default(rows):
    """created_at ASC, id ASC tie-break (PRD 2.3 default ordering)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def sort_by(rows, key_field):
    """<key_field> ASC, created_at ASC, id ASC (PRD 2.3 ordering exceptions)."""
    return sorted(rows, key=lambda r: (r[key_field], r["created_at"], r["id"]))
