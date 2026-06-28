"""In-memory data store (PRD: state wiped on every fresh boot).

NO seeding, preloading, or hardcoded entities. Every collection starts empty;
tests build all state via the API surface.
"""
from datetime import timezone

from clock import clock
from util import new_uuid, iso_z


class Store:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.studios = {}
        self.rooms = {}
        self.bikes = {}
        self.instructors = {}
        self.sessions = {}
        self.members = {}
        self.credit_packs = {}
        self.reservations = {}
        self.waitlist_entries = {}
        self.products = {}
        self.retail_orders = {}
        self.penalty_charges = {}
        # Monotonic sequence to provide a stable secondary sort for items
        # created within the same logical-clock instant (created_at tie-breaks).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def stamp_new(record):
    """Attach common system fields on create (PRD §2.4): id, created_at,
    updated_at, version, plus an internal sequence for stable tie-breaks."""
    now = clock.now()
    record["id"] = new_uuid()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation bump (PRD §2.4 / §2.7): updated_at refreshed, version +1."""
    record["updated_at"] = clock.now()
    record["version"] = record["version"] + 1
    return record


def reset():
    """Re-initialize the store (also resets the logical clock to default)."""
    global db
    db = Store()
    from clock import DEFAULT_NOW
    clock.set(DEFAULT_NOW)
