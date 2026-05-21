"""Serializers — shape stored entities for the response envelope.

Every entity is stored as a flat dict with both server-managed and input
fields. Serializers are intentionally permissive (they spread the dict)
so newly-added fields propagate without a code change.
"""
from __future__ import annotations

from typing import Any


def _shallow_copy(entity: dict[str, Any]) -> dict[str, Any]:
    return dict(entity)


def marina_view(m: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(m)


def boater_view(b: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(b)


def vessel_view(v: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(v)


def slip_view(s: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(s)


def reservation_view(r: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(r)


def waitlist_view(w: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(w)


def transfer_view(t: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(t)


def pump_out_view(p: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(p)


def reading_view(u: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(u)


def settlement_view(s: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(s)


def policy_view(p: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(p)


def tow_contract_view(c: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(c)


def tow_event_view(e: dict[str, Any]) -> dict[str, Any]:
    return _shallow_copy(e)
