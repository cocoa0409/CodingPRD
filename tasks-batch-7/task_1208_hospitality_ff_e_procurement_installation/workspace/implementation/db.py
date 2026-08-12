"""In-memory data store. Empty on every boot; no seeding, no persistence."""
import itertools
import threading
import uuid
from datetime import datetime, timezone, timedelta

STORE = {
    "projects": {},
    "budget_lines": {},
    "spec_items": {},
    "bids": {},
    "purchase_orders": {},
    "po_lines": {},
    "shipments": {},
    "receiving_events": {},
    "damage_claims": {},
    "rooms": {},
    "installation_windows": {},
    "installation_tasks": {},
    "attic_movements": {},
    "change_orders": {},
}

_seq = itertools.count(1)
_ts_lock = threading.Lock()
_last_ts = None


def now_ts():
    """ISO 8601 UTC timestamp with three fractional digits; strictly increasing."""
    global _last_ts
    with _ts_lock:
        t = datetime.now(timezone.utc)
        if _last_ts is not None and t <= _last_ts:
            t = _last_ts + timedelta(milliseconds=1)
        _last_ts = t
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def create(kind, fields):
    """Create a primary resource with common fields (id/created_at/updated_at/version)."""
    ts = now_ts()
    e = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    e.update(fields)
    e["_seq"] = next(_seq)
    STORE[kind][e["id"]] = e
    return e


def create_event(fields):
    """Create an append-only event row (AtticStockMovement): id + created_at only."""
    e = {"id": new_id(), "created_at": now_ts()}
    e.update(fields)
    e["_seq"] = next(_seq)
    STORE["attic_movements"][e["id"]] = e
    return e


def _bumped():
    from flask import g
    if not hasattr(g, "_bumped"):
        g._bumped = set()
    return g._bumped


def touch(e):
    """Mark an existing resource mutated: version += 1 and updated_at refreshed.

    At most one bump per resource per request; derived-field recomputes call
    touch only when a stored value actually changed, so a no-change recompute
    is not a mutation.
    """
    b = _bumped()
    if e["id"] in b:
        return
    b.add(e["id"])
    e["version"] += 1
    e["updated_at"] = now_ts()


def pub(e):
    """Public serialization: strip internal keys."""
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sorted_items(rows):
    """List order: created_at ascending (insertion order breaks same-ms ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
