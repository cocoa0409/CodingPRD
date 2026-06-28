"""In-memory data store (PRD §2.4).

Storage is purely in-memory: dicts keyed by id. There is NO seeding at startup —
every entity is built by the API. Each start.sh re-invocation imports this module
fresh, wiping all state.
"""
import uuid

import clock


class Store:
    """A single collection of one entity type keyed by id, preserving insertion
    order (Python dicts preserve insertion order, used for created_at sorting)."""

    def __init__(self):
        self.items = {}
        self._seq = 0  # monotonic insertion sequence for stable created_at sort

    def next_seq(self):
        self._seq += 1
        return self._seq


class DB:
    def __init__(self):
        # First-class records (carry id/created_at/updated_at/version)
        self.membership_plans = Store()
        self.lounges = Store()
        self.members = Store()
        self.eligibility_cards = Store()
        self.visits = Store()
        self.guests = Store()
        self.day_passes = Store()
        self.shower_suites = Store()
        self.shower_reservations = Store()
        # Append-only event records (carry only id/created_at)
        self.settlements = Store()
        self.ledger_entries = Store()


db = DB()


def new_id():
    return str(uuid.uuid4())


def make_common_fields():
    """System fields for a full first-class record at creation."""
    ts = clock.now_iso_millis()
    return {
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def make_event_fields():
    """System fields for an append-only event record (id + created_at only)."""
    return {
        "created_at": clock.now_iso_millis(),
    }


def touch(record):
    """Bump updated_at and version on a first-class mutated record."""
    record["updated_at"] = clock.now_iso_millis()
    record["version"] = record.get("version", 1) + 1
