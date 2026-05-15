"""Entity serializers — produce stable, JSON-friendly snapshots."""
from __future__ import annotations

import copy
from typing import Any


def _copy(entity: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(entity)


def serialize_cabinet(c: dict[str, Any]) -> dict[str, Any]:
    return _copy(c)


def serialize_compartment(c: dict[str, Any]) -> dict[str, Any]:
    return _copy(c)


def serialize_pricing_profile(p: dict[str, Any]) -> dict[str, Any]:
    return _copy(p)


def serialize_rental(r: dict[str, Any]) -> dict[str, Any]:
    return _copy(r)


def serialize_insurance_claim(c: dict[str, Any]) -> dict[str, Any]:
    return _copy(c)


def serialize_repair_ticket(t: dict[str, Any]) -> dict[str, Any]:
    return _copy(t)


def serialize_revenue_record(r: dict[str, Any]) -> dict[str, Any]:
    return _copy(r)


def serialize_audit_event(a: dict[str, Any]) -> dict[str, Any]:
    return _copy(a)
