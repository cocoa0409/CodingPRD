"""Helpers to serialize internal entity dicts to JSON-safe output."""
from __future__ import annotations

from typing import Any, Dict


def serialize_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy that is JSON-safe. Internal helper fields are dropped."""
    if entity is None:
        return None
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = v
    return out


def serialize_list(entities):
    return [serialize_entity(e) for e in entities]
