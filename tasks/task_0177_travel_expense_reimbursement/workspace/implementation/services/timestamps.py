"""Common-field helpers: created_at, updated_at, version."""
from __future__ import annotations

from typing import Any, Dict

from core.utils import new_id, now_iso


def stamp_create(record: Dict[str, Any], with_version: bool = True) -> Dict[str, Any]:
    """Populate id/created_at/updated_at/version on a fresh record."""
    if "id" not in record or not record["id"]:
        record["id"] = new_id()
    ts = now_iso()
    record["created_at"] = ts
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def stamp_update(record: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh updated_at and bump version by 1."""
    record["updated_at"] = now_iso()
    record["version"] = int(record.get("version", 0)) + 1
    return record
