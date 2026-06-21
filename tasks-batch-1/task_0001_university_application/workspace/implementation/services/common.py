"""Shared helpers for entity bookkeeping."""
from __future__ import annotations

import db


def new_common_fields() -> dict:
    """The four server-managed fields at creation time."""
    now = db.now_iso()
    return {
        "id": db.new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity: dict):
    """Refresh updated_at and bump version."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1
