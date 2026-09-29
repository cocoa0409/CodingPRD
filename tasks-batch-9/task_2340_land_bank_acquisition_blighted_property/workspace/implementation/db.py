"""In-memory data store.

The store is EMPTY on every boot: no entity is ever seeded, preloaded or
hardcoded. Every record is created through the declared API surface.
"""
import uuid

from flask import g

from clock import DEFAULT_CLOCK


class Store(object):
    def __init__(self):
        self.properties = {}
        self.funding_sources = {}
        self.packets = {}
        self.title_actions = {}
        self.contractors = {}
        self.orders = {}
        self.runs = {}
        self.applicants = {}
        self.adjacencies = {}
        self.hearings = {}
        self.applications = {}
        self.screenings = {}
        self.agreements = {}
        self._seq = 0
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current logical instant."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """Common system-managed fields (PRD 2.4)."""
    record = {
        "id": new_id(),
        "_seq": db.next_seq(),
        "created_at": now(),
    }
    if versioned:
        record["updated_at"] = now()
        record["version"] = 1
    return record


def touch(record):
    """Bump version/updated_at once per request for a mutated record."""
    if record is None or "version" not in record:
        return
    try:
        touched = g._touched
    except (AttributeError, RuntimeError):
        touched = None
    key = id(record)
    if touched is None:
        touched = set()
        try:
            g._touched = touched
        except RuntimeError:
            pass
    if key in touched:
        return
    touched.add(key)
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now()


def ordered(records):
    """Default list order: created_at ascending, stable by insertion order."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
