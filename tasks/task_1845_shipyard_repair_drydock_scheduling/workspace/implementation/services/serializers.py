"""Serializers: strip internal fields (underscore-prefixed) before output and
attach derived fields that are computed at read time (PRD 3.4: `ready`)."""

from __future__ import annotations

import db


def serialize(entity: dict) -> dict:
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items: list) -> list:
    return [serialize(it) for it in items]


def work_item_ready(item: dict) -> bool:
    """Derived, never stored: true exactly when the item is PLANNED and every
    item named in depends_on_ids is COMPLETE."""
    if item.get("status") != "PLANNED":
        return False
    for dep_id in item.get("depends_on_ids") or []:
        dep = db.work_items.get(dep_id)
        if dep is None or dep.get("status") != "COMPLETE":
            return False
    return True


def serialize_work_item(item: dict) -> dict:
    out = serialize(item)
    out["ready"] = work_item_ready(item)
    return out


def serialize_work_item_list(items: list) -> list:
    return [serialize_work_item(it) for it in items]
