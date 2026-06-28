"""In-memory data store. PRD §2.4: most resources carry id (UUID, no prefix),
created_at, updated_at, version. HealthMarkerResult and MarkerCatalogEntry are
lighter: only id and created_at (no updated_at, no version).

The store starts EMPTY on every boot. No seeding, preloading, or hardcoded
entities. Every entity is constructed by tests via the declared API surface.
"""
import itertools
import threading
import uuid

from clock import clock, format_iso8601

# Monotonic creation sequence to provide a stable tiebreaker for created_at
# ascending sort, since the logical clock may not advance between creates.
_seq = itertools.count(1)
_lock = threading.RLock()


def new_id():
    # UUID with no type prefix (PRD §2.4)
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.accounts = {}
        self.pets = {}
        self.kits = {}
        self.samples = {}
        self.genotyping_runs = {}
        self.reports = {}
        self.health_marker_results = {}
        self.relative_matches = {}
        self.share_links = {}
        self.subscriptions = {}
        self.data_requests = {}
        self.marker_catalog = {}


db = Store()


def _now_iso():
    return format_iso8601(clock.now())


def create_versioned(collection, fields):
    """Create a full first-class entity with id/created_at/updated_at/version."""
    rid = new_id()
    rec = dict(fields)
    rec["id"] = rid
    rec["created_at"] = _now_iso()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next(_seq)
    collection[rid] = rec
    return rec


def create_light(collection, fields):
    """Create a lightweight, immutable record: only id and created_at."""
    rid = new_id()
    rec = dict(fields)
    rec["id"] = rid
    rec["created_at"] = _now_iso()
    rec["_seq"] = next(_seq)
    collection[rid] = rec
    return rec


def touch(rec):
    """Mutation: refresh updated_at and increment version by exactly one."""
    rec["updated_at"] = _now_iso()
    rec["version"] = rec.get("version", 0) + 1
    return rec
