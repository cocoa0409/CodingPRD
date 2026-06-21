"""In-memory data store. Starts EMPTY on every boot — never seeded.

Each entity collection is a dict keyed by id (UUID4 string, no type prefix).
Common fields per PRD §2.4: id, created_at, updated_at, version.
"""
import uuid

import clock

# One dict per entity collection.
sites = {}
floors = {}
hosts = {}
watchlist_entries = {}
meeting_rooms = {}
parking_spaces = {}
visits = {}
agreements = {}
contractor_passes = {}
deliveries = {}
evacuation_events = {}


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Attach common create fields. version starts at 0 (PRD §2.4 non-negative int)."""
    ts = clock.now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 0
    return record


def touch(record):
    """Record a mutation: bump updated_at and version by 1 (PRD §2.4)."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 0) + 1
    return record
