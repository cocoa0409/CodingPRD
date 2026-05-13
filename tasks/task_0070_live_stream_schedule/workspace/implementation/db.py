"""In-memory data store and entity-lifecycle helpers."""

from __future__ import annotations

import threading
import uuid
from copy import deepcopy

import clock


_lock = threading.RLock()


def lock():
    return _lock


# Each top-level key is a bag of entities keyed by id.
_state = {
    "streamers": {},
    "studios": {},
    "time_slot_configs": {},
    "applications": {},
    "approvals": {},
    "products": {},
    "product_associations": {},
    "invoices": {},
    "settlements": {},
    "violations": {},
    "appeals": {},
    "external_events": {},
    "audit_logs": {},
}


def reset_all():
    with _lock:
        for k in list(_state.keys()):
            _state[k].clear()


def store(kind: str) -> dict:
    return _state[kind]


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

# Heavyweight entity kinds carry created_at, updated_at, and version.
HEAVY_KINDS = {
    "streamers",
    "studios",
    "applications",
    "products",
    "product_associations",
    "invoices",
    "settlements",
    "violations",
    "appeals",
}

# Lightweight log-style entities carry only id and created_at.
LIGHT_KINDS = {
    "time_slot_configs",
    "approvals",
    "external_events",
    "audit_logs",
}


def create_entity(kind: str, payload: dict) -> dict:
    """Persist `payload` as a fresh entity, stamping system fields appropriately."""
    with _lock:
        eid = new_id()
        ts = clock.format_iso(clock.now())
        entity = dict(payload)
        entity["id"] = eid
        entity["created_at"] = ts
        if kind in HEAVY_KINDS:
            entity["updated_at"] = ts
            entity["version"] = 1
        _state[kind][eid] = entity
        return deepcopy(entity)


def update_entity(kind: str, eid: str, mutate) -> dict:
    """Mutate an entity in place via a callback. Caller is responsible for
    pre-checks. Bumps `version` and refreshes `updated_at` for heavy kinds.

    Returns a deepcopy of the updated entity.
    """
    with _lock:
        entity = _state[kind].get(eid)
        if entity is None:
            raise KeyError(eid)
        mutate(entity)
        if kind in HEAVY_KINDS:
            entity["version"] = entity.get("version", 1) + 1
            entity["updated_at"] = clock.format_iso(clock.now())
        return deepcopy(entity)


def get_entity(kind: str, eid: str) -> dict | None:
    with _lock:
        entity = _state[kind].get(eid)
        return deepcopy(entity) if entity is not None else None


def list_entities(kind: str, predicate=None) -> list:
    with _lock:
        items = list(_state[kind].values())
        if predicate is not None:
            items = [it for it in items if predicate(it)]
        items.sort(key=lambda x: x.get("created_at", ""))
        return [deepcopy(it) for it in items]


def raw_get(kind: str, eid: str):
    """Return the live (non-copied) entity dict. Caller must hold the lock or
    treat the returned value as read-only-by-convention.
    """
    return _state[kind].get(eid)


def raw_all(kind: str):
    return list(_state[kind].values())
