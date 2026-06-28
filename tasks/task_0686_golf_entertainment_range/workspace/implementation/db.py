"""In-memory data store (PRD §2.4).

Storage is in-memory ONLY — plain dicts keyed by id. There is NO persistence,
no SQLite, no JSON dump, no /tmp cache. Every process boot starts empty; the
store is NEVER seeded or preloaded with any entity. Tests build all state via
the declared API surface.

Common system fields (PRD §2.4):
  - id              : server-minted UUID, no prefix
  - created_at      : ISO 8601 UTC, three fractional digits (logical clock)
  - updated_at      : refreshed on every mutation (incl. cascades)
  - version         : integer, begins at 1, +1 on every mutation

GiftCard and Charge are the exceptions: immutable, only id + created_at, no
updated_at / version (PRD §2.4).
"""

import uuid

from clock import clock


class DB:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.venues = {}
        self.bays = {}
        self.members = {}
        self.game_cards = {}
        self.gift_cards = {}
        self.reservations = {}
        self.sessions = {}
        self.event_packages = {}
        self.fb_tabs = {}
        self.queue_tickets = {}
        self.lessons = {}
        self.charges = {}
        # Monotonic counter to break created_at ties deterministically so that
        # list ordering by created_at is stable even when many records share the
        # same logical-clock instant.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def new_id():
        return str(uuid.uuid4())


db = DB()


def new_id():
    return DB.new_id()


def stamp_common(record):
    """Initialise common system fields on a freshly created versioned record."""
    now = clock.now_iso()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_immutable(record):
    """Initialise the two immutable resources (GiftCard, Charge): id + created_at only."""
    record["id"] = record.get("id") or new_id()
    record["created_at"] = clock.now_iso()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mark a versioned record as mutated: refresh updated_at, bump version (PRD §2.4)."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
