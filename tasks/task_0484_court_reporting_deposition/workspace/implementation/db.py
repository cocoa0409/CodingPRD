"""In-memory data store (PRD §2.4 common fields & versioning).

Storage is in-memory only. The store starts EMPTY on every boot; no entity is
ever seeded, preloaded, or hardcoded at startup.
"""
import uuid
from datetime import timezone

from clock import clock


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def iso_ts(dt):
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        # One dict per entity, keyed by id. All start empty.
        self.cases = {}
        self.attorneys = {}
        self.resources = {}
        self.jobs = {}
        self.assignments = {}
        self.realtime_streams = {}
        self.transcript_orders = {}
        self.exhibits = {}
        self.errata = {}
        self.invoices = {}
        self._seq = 0

    def next_seq(self):
        """Monotonic sequence for stable creation ordering / tie-breaking."""
        self._seq += 1
        return self._seq


db = Store()


def stamp_create(entity):
    """Set system-managed common fields on create (PRD §2.4)."""
    now = clock.now()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Record a mutation: refresh updated_at and increment version (PRD §2.4)."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 1) + 1
    return entity
