"""In-memory data store.

Every collection starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded: all state is created through the API surface.
"""
import itertools
import uuid

from flask import g

import clock

_seq = itertools.count(1)

stores = {}
hour_windows = {}
channels = {}
menu_versions = {}
menu_items = {}
listings = {}
availability_events = {}
orders = {}
order_lines = {}
injection_attempts = {}
courier_networks = {}
assignments = {}
adjustments = {}
statements = {}

ALL_COLLECTIONS = (
    stores, hour_windows, channels, menu_versions, menu_items, listings,
    availability_events, orders, order_lines, injection_attempts,
    courier_networks, assignments, adjustments, statements,
)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def record(journal=False):
    """Create the common system-managed properties (PRD 2.5)."""
    created = clock.now()
    rec = {"id": new_id(), "created_at": created, "_seq": next_seq()}
    if not journal:
        rec["updated_at"] = created
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version, at most once per request."""
    if rec is None or "version" not in rec:
        return
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        seen = set()
        try:
            g._touched = seen
        except RuntimeError:
            pass
    key = id(rec)
    if key in seen:
        return
    seen.add(key)
    rec["updated_at"] = clock.now()
    rec["version"] = rec["version"] + 1


def sorted_records(collection, predicate=None):
    """created_at ascending, insertion order as the deterministic tie-break."""
    values = [r for r in collection.values() if predicate is None or predicate(r)]
    values.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return values
