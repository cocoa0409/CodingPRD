"""In-memory data store. All state is process-local and wiped on restart.

No seeding, no preloading, no persistence. Tests build every entity via the
declared API surface.
"""
import uuid

from clock import clock, format_iso8601


class Store:
    def __init__(self):
        self.creditors = {}
        self.consumers = {}
        self.accounts = {}
        self.communication_attempts = {}
        self.disputes = {}
        self.arrangements = {}
        self.payments = {}
        self.skip_traces = {}
        self.bureau_furnishings = {}
        self.bureau_disputes = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(entity):
    """Set id/created_at/updated_at/version common fields on a new entity dict."""
    now = format_iso8601(clock.now)
    entity.setdefault("id", new_id())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def touch(entity):
    """Bump updated_at and version on any mutation of the entity."""
    entity["updated_at"] = format_iso8601(clock.now)
    entity["version"] = entity.get("version", 1) + 1
    return entity
