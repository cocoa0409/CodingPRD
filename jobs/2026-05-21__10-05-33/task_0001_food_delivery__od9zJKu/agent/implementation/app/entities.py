"""Shared entity utilities: versioning, timestamps, projections."""
from __future__ import annotations

from .clock import iso_now
from .envelope import new_uuid


def init_versioned(entity_type: str) -> dict:
    """Build base dict with id/created_at/updated_at/version."""
    now = iso_now()
    return {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_type": entity_type,
    }


def init_unversioned(entity_type: str) -> dict:
    """Build base dict with only id and created_at (Assignment, RouteGroup, Fine)."""
    now = iso_now()
    return {
        "id": new_uuid(),
        "created_at": now,
        "_type": entity_type,
    }


def bump(entity: dict) -> None:
    """Refresh updated_at and increment version on versioned entities."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity.get("version", 1) + 1


def project(entity: dict, exclude: tuple[str, ...] = ()) -> dict:
    """Return a public projection: drop internal-prefixed keys (_*) and excluded keys."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if k in exclude:
            continue
        out[k] = v
    return out
