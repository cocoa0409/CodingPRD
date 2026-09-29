"""In-memory data store.  Nothing is ever seeded: every entity is created by
a client call to a declared endpoint.  The store is a plain set of dicts keyed
by id and is discarded when the process exits."""
import itertools
import uuid
from datetime import datetime

from timeutil import UTC, fmt_dt

# The logical clock reads exactly this instant before it has ever been set
# (PRD 2.4).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.schools = {}
        self.intersections = {}
        self.studies = {}
        self.guards = {}
        self.posts = {}
        self.assignments = {}
        self.absences = {}
        self.walking_routes = {}
        self.complaints = {}
        self.grant_programs = {}
        self.projects = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """Current value of the logical program clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_entity():
    """The four system-managed properties every resource carries (PRD 2.5)."""
    stamp = fmt_dt(now())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


# --- per-request mutation bookkeeping --------------------------------------
def _touched_set():
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        if not hasattr(g, "_touched"):
            g._touched = set()
        return g._touched
    except Exception:
        return None


def touch(entity):
    """Record a mutation: refresh updated_at from the logical clock and
    increment version by exactly one for this request (PRD 2.5)."""
    if entity is None:
        return
    seen = _touched_set()
    key = entity.get("id")
    if seen is not None and key in seen:
        entity["updated_at"] = fmt_dt(now())
        return
    if seen is not None:
        seen.add(key)
    entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = fmt_dt(now())


def public(entity):
    """Strip internal bookkeeping keys from an entity before serialisation."""
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_key(entity):
    return (entity.get("created_at") or "", entity.get("_seq") or 0)


def sorted_records(records):
    return sorted(records, key=sort_key)
