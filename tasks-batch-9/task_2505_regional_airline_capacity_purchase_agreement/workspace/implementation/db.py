"""In-memory data store.

Storage is process-local Python dicts keyed by id.  The store starts completely
empty on every boot: no entity is ever seeded, preloaded or hardcoded here.
"""

from flask import g

from core import clock, new_id

COLLECTIONS = (
    "agreements",
    "crew_bases",
    "aircraft",
    "pilots",
    "schedule_cycles",
    "flight_legs",
    "cancellation_claims",
    "passthrough_claims",
    "scorecards",
    "invoices",
    "brand_audits",
    "negotiations",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})


store = Store()


def new_entity(fields):
    """Mint a resource with the four common system properties (PRD 2.4)."""
    stamp = clock.iso()
    entity = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    entity.update(fields)
    return entity


def touch(entity):
    """Refresh updated_at and bump version at most once per triggering request."""
    entity["updated_at"] = clock.iso()
    try:
        touched = g.touched
    except (AttributeError, RuntimeError):
        touched = None
    if touched is None:
        try:
            touched = set()
            g.touched = touched
        except RuntimeError:
            entity["version"] += 1
            return
    key = entity["id"]
    if key not in touched:
        entity["version"] += 1
        touched.add(key)


def sort_key(entity):
    """PRD 2.3 default list ordering: created_at ASC, then id ASC."""
    return (entity["created_at"], entity["id"])


def ordered(entities):
    return sorted(entities, key=sort_key)


def values(collection):
    return ordered(collection.values())


def public(entity):
    """Serialise a stored entity: every field except internal underscore keys."""
    return dict((name, value) for name, value in entity.items()
                if not name.startswith("_"))
