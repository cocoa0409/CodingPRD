"""In-memory data store. All state lives in module-level dicts.

A fresh process (each start.sh re-invocation) starts completely empty.
NO seeding, NO preloading.
"""
import uuid

import clock


class Store:
    def __init__(self):
        # Each collection is keyed by id.
        self.customers = {}
        self.technicians = {}
        self.routes = {}
        self.properties = {}
        self.quotes = {}
        self.quote_line_items = {}
        self.recurring_plans = {}
        self.visits = {}
        self.crew_assignments = {}
        self.weather_windows = {}
        self.photo_sets = {}
        self.invoices = {}
        self.satisfaction_claims = {}
        # Monotonic creation sequence to give a stable created_at tiebreak
        # (the logical clock can be set to the same instant repeatedly).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def reset():
    global db
    db = Store()


def new_id():
    return str(uuid.uuid4())


def common_create_fields():
    """id, created_at, updated_at, version for full primary resources."""
    ts = clock.now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def append_only_fields():
    """id, created_at only (QuoteLineItem, PhotoSet)."""
    return {
        "id": new_id(),
        "created_at": clock.now_iso(),
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Mark a primary resource as mutated: bump updated_at and version."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] = entity.get("version", 1) + 1
