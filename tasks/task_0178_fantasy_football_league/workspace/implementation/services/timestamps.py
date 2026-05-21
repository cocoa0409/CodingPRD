"""Common-field handling for entities with id/created_at/updated_at/version."""
from __future__ import annotations

from typing import Any, Dict

from core.utils import format_iso, new_id, now_iso


def stamp_create(entity: Dict[str, Any], with_version: bool = True) -> Dict[str, Any]:
    """Apply id and created_at/updated_at/version on a new entity."""
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def stamp_update(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Bump updated_at and version on an existing entity."""
    if "version" in entity:
        entity["updated_at"] = now_iso()
        entity["version"] = int(entity.get("version", 0)) + 1
    return entity


def iso_from_dt(dt) -> str:
    return format_iso(dt) if dt else None
