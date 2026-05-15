"""Serialize entities to JSON shapes returned by the API."""
from __future__ import annotations

from typing import Any


COMMON_KEYS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_KEYS = ("id", "created_at")


def _copy(entity: dict[str, Any], *fields: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields:
        if f in entity:
            out[f] = entity[f]
    return out


def serialize_project(p: dict[str, Any]) -> dict[str, Any]:
    return dict(p)


def serialize_contraindication_rule(r: dict[str, Any]) -> dict[str, Any]:
    return dict(r)


def serialize_consumable_sku(s: dict[str, Any]) -> dict[str, Any]:
    return dict(s)


def serialize_room(r: dict[str, Any]) -> dict[str, Any]:
    return dict(r)


def serialize_customer(c: dict[str, Any]) -> dict[str, Any]:
    return dict(c)


def serialize_plan(p: dict[str, Any]) -> dict[str, Any]:
    return dict(p)


def serialize_appointment(a: dict[str, Any]) -> dict[str, Any]:
    return dict(a)


def serialize_operative_record(o: dict[str, Any]) -> dict[str, Any]:
    return dict(o)


def serialize_followup(f: dict[str, Any]) -> dict[str, Any]:
    return dict(f)


def serialize_adverse_event(a: dict[str, Any]) -> dict[str, Any]:
    return dict(a)


def serialize_installment(i: dict[str, Any]) -> dict[str, Any]:
    return dict(i)


def serialize_audit(a: dict[str, Any]) -> dict[str, Any]:
    return dict(a)


def serialize_sync_event(e: dict[str, Any]) -> dict[str, Any]:
    return dict(e)
