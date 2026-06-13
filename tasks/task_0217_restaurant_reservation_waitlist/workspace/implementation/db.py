"""In-memory data store.

Every collection is a plain dict keyed by the entity's UUID id. The store
starts EMPTY on every boot — nothing is seeded. Tests construct every entity
they need through the declared API surface.

Resources carry system-managed fields: id (UUID, no prefix), created_at,
updated_at, version (PRD §2.4). SpecialRequest and Notification are
append-only and carry only id + created_at (no updated_at, no version).
"""
import itertools
import uuid

import clock
from timeutil import format_iso

# One dict per entity collection.
restaurants = {}
dining_areas = {}
tables = {}
service_periods = {}
customers = {}
reservations = {}
waitlist_entries = {}
deposit_holds = {}
special_requests = {}
notifications = {}
private_dining_events = {}

# Monotonic counter giving every record a stable creation order. Used as the
# default list sort (created_at ascending) so that records created within the
# same pinned-clock instant still order deterministically by creation.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def base_fields(versioned=True):
    """Fresh system fields for a new entity at the current server clock."""
    ts = clock.now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutated versioned entity."""
    rec["updated_at"] = clock.now()
    if "version" in rec:
        rec["version"] = rec["version"] + 1


def reset_all():
    """Wipe all state (boot-time freshness). Not exposed via the API."""
    for coll in (
        restaurants, dining_areas, tables, service_periods, customers,
        reservations, waitlist_entries, deposit_holds, special_requests,
        notifications, private_dining_events,
    ):
        coll.clear()
    clock.reset()


# ---- serialization -----------------------------------------------------------

_DATETIME_FIELDS = {
    "created_at", "updated_at", "reservation_start", "turn_window_end",
    "release_at", "requested_start", "joined_at", "notify_expires_at",
    "event_start", "event_end",
}


def serialize(rec):
    """Project an internal record into its public JSON form.

    Strips private keys (those starting with '_') and renders datetime
    fields as ISO 8601 UTC with three fractional digits.
    """
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if k in _DATETIME_FIELDS:
            out[k] = format_iso(v) if v is not None else None
        else:
            out[k] = v
    return out
