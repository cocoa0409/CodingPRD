"""In-memory data store.

Every collection is a plain dict keyed by the entity's UUID id. The store
starts EMPTY on every process boot — no seeding, no preload. Tests construct
all state through the declared API surface.
"""
import threading
import uuid

from timeutil import now_iso

# One dict per entity collection, keyed by id.
centers = {}
donors = {}
deferrals = {}
slots = {}
appointments = {}
screenings = {}
donations = {}
test_results = {}
blood_units = {}
adverse_reactions = {}
recall_events = {}
inventory_buckets = {}

# Global lock so each request mutates the store atomically. Flask's default
# dev server is threaded; this keeps cascades and OCC consistent.
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    """Populate the common system quartet on a freshly created record."""
    ts = now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Bump updated_at + version on any mutation (including cascade hops)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
