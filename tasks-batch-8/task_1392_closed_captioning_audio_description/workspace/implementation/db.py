"""In-memory data store and logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty on
every boot; nothing is seeded, preloaded, or persisted.
"""
import itertools
import uuid
from datetime import datetime, timezone


class _Clock:
    """Logical clock. Startup default is exactly 2026-08-01T00:00:00Z and the
    clock never falls back to wall-clock time."""

    def __init__(self):
        self._current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt


CLOCK = _Clock()


def now():
    return CLOCK.now()


class Store:
    def __init__(self):
        self.clients = {}
        self.media_assets = {}
        self.work_orders = {}
        self.caption_tracks = {}
        self.qc_reviews = {}
        self.ad_tracks = {}
        self.live_events = {}
        self.stenographers = {}
        self.assignments = {}
        self.complaints = {}
        self.conversion_jobs = {}
        self.archive_items = {}
        self._seq = itertools.count(1)


DB = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    """Populate system fields for a freshly created record (version starts at 1)."""
    t = now()
    rec["id"] = new_id()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next(DB._seq)
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version by one."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
    return rec
