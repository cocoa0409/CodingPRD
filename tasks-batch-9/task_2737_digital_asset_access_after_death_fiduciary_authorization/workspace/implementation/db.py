"""In-memory data store. Starts completely empty on every boot -- nothing is
seeded, preloaded or hardcoded. Every record is created by an API call.
"""
import uuid

from clock import CLOCK


class Store(object):
    COLLECTIONS = (
        "platforms",
        "estates",
        "fiduciaries",
        "documents",
        "directives",
        "assets",
        "terms",
        "requests",
        "grants",
        "designations",
        "elections",
        "orders",
        "claims",
        "runs",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    """Attach the system-managed common fields to a brand new record."""
    now = CLOCK.iso()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = DB.next_seq()
    return record


def bump(record):
    """Advance a record's version and updated_at because a field changed."""
    record["version"] = record.get("version", 0) + 1
    record["updated_at"] = CLOCK.iso()
    return record


def order_key(record):
    """created_at ascending, insertion order breaking exact ties."""
    return (record.get("created_at") or "", record.get("_seq") or 0)


def sorted_records(records):
    return sorted(records, key=order_key)


def all_sorted(collection):
    return sorted_records(list(collection.values()))
