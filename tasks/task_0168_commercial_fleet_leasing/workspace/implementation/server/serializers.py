"""Serializers — return entity dicts as-is (we don't store internal-only fields)."""
from __future__ import annotations

from typing import Any


def _copy(entity: dict[str, Any]) -> dict[str, Any]:
    return dict(entity)


def lessee_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def vehicle_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def lease_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def fuel_card_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def fuel_card_txn_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def telematics_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def maintenance_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def collision_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def settlement_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)


def ifta_view(e: dict[str, Any]) -> dict[str, Any]:
    return _copy(e)
