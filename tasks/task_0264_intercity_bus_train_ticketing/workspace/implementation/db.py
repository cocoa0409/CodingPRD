"""In-memory data store. All state lives in module-level dicts keyed by id.

No persistence, no seeding: every boot starts empty (PRD/skill requirement).
Tests construct all entities via the API surface.
"""
import uuid
import itertools

import clock
from timeutil import iso_now

# Entity tables: id -> record dict
operators = {}
fare_classes = {}
routes = {}
service_dates = {}
passengers = {}
travel_passes = {}
bookings = {}
booking_legs = {}
tickets = {}
baggage_items = {}
accessibility_requests = {}
settlement_notes = {}

ALL_TABLES = [
    operators, fare_classes, routes, service_dates, passengers, travel_passes,
    bookings, booking_legs, tickets, baggage_items, accessibility_requests,
    settlement_notes,
]

# Monotonic creation sequence so created_at ties still sort deterministically
# in insertion order (PRD 2.3: list sorted by created_at ascending).
_seq = itertools.count(1)


def reset():
    for t in ALL_TABLES:
        t.clear()
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp_create(rec, with_version=True):
    """Set created_at/updated_at (+version) on a freshly created record."""
    ts = iso_now(clock.now())
    rec["created_at"] = ts
    rec["_seq"] = next_seq()
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version and refresh updated_at on any mutation (PRD 2.4)."""
    rec["updated_at"] = iso_now(clock.now())
    rec["version"] = rec.get("version", 0) + 1
    return rec


def public(rec):
    """Strip internal-only keys (those prefixed with '_') for API output."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
