"""Common entity helpers — common-fields handling, version bumping."""
from __future__ import annotations

from typing import Any, Dict

import db
from clock import now_iso


def init_full(entity: Dict[str, Any]) -> None:
    """Stamp common-fields-full (id + created_at + updated_at + version=1).

    The caller is responsible for putting the entity into its table.
    """
    if "id" not in entity:
        entity["id"] = db.new_uuid()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1


def init_bare(entity: Dict[str, Any]) -> None:
    """Stamp common-fields-bare (id + created_at)."""
    if "id" not in entity:
        entity["id"] = db.new_uuid()
    entity["created_at"] = now_iso()


def bump(entity: Dict[str, Any]) -> None:
    """Increment version + refresh updated_at after a successful mutation."""
    entity["version"] = int(entity.get("version", 1)) + 1
    entity["updated_at"] = now_iso()
