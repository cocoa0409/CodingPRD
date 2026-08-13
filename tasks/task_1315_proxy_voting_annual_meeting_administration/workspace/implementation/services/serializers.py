"""Entity serialization: copy all public fields, strip internal bookkeeping."""

from __future__ import annotations


def serialize(entity: dict | None) -> dict | None:
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items: list) -> list:
    return [serialize(it) for it in items]
