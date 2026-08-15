"""Serializers: strip internal fields (underscore-prefixed) before output."""

from __future__ import annotations


def serialize(entity: dict) -> dict:
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items: list) -> list:
    return [serialize(it) for it in items]
