"""In-memory data store (PRD §2.4 common fields, logical clock).

Storage is in-memory only — Python dicts keyed by UUID id. The store starts
empty on every boot; nothing is seeded. start.sh re-invocation wipes all
state and boots fresh.
"""
import threading
import uuid
from datetime import datetime, timezone

from clock import Clock, iso


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        # One dict per entity type, keyed by id.
        self.venues = {}
        self.memberships = {}
        self.shows = {}
        self.show_bookings = {}
        self.group_bookings = {}
        self.programs = {}
        self.registrations = {}
        self.rentals = {}
        self.sponsors = {}
        self.contributions = {}
        self.accommodations = {}
        # Monotonic sequence to break created_at ties deterministically.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


# Single global instance. Recreated fresh on every process boot.
db = DB()


def new_record(with_version=True):
    """Create the server-managed common fields (PRD §2.4).

    id: server-minted UUID, no type prefix.
    created_at: ISO8601 UTC, three fractional digits, wall-clock at creation
                (used only for stable creation ordering of records).
    updated_at / version: present on mutable resources.
    _created_seq: internal tie-breaker for created_at ASC ordering.
    """
    now = datetime.now(timezone.utc)
    rec = {
        "id": db.new_id(),
        "created_at": iso(now),
        "_created_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = iso(now)
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutable resource (PRD §2.4)."""
    rec["updated_at"] = iso(datetime.now(timezone.utc))
    if "version" in rec:
        rec["version"] += 1
