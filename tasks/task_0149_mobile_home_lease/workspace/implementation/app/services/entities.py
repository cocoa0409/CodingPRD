"""Helpers for managing the common audit envelope and entity lookups."""
from __future__ import annotations

from typing import Any, Optional

from ..clock import clock, format_timestamp
from ..errors import ApiError
from ..store import new_id, store


def init_common_fields(obj: dict[str, Any]) -> dict[str, Any]:
    """Initialise id/created_at/updated_at/version on a fresh entity."""
    ts = clock.iso_now()
    obj.setdefault("id", new_id())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def touch(obj: dict[str, Any]) -> None:
    """Bump updated_at and version on an existing entity."""
    obj["updated_at"] = clock.iso_now()
    obj["version"] = obj.get("version", 1) + 1


def init_bill_fields(obj: dict[str, Any]) -> dict[str, Any]:
    """Utility bills carry only id + created_at (no updated_at, no version)."""
    obj.setdefault("id", new_id())
    obj["created_at"] = clock.iso_now()
    return obj


# Resource fetchers raising ERR_RESOURCE_NOT_FOUND if missing


def get_park_or_404(park_id: str) -> dict[str, Any]:
    park = store.parks.get(park_id)
    if park is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Park {park_id} not found.")
    return park


def get_lot_or_404(lot_id: str) -> dict[str, Any]:
    lot = store.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Lot {lot_id} not found.")
    return lot


def get_home_or_404(home_id: str) -> dict[str, Any]:
    home = store.homes.get(home_id)
    if home is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Home {home_id} not found.")
    return home


def get_resident_or_404(resident_id: str) -> dict[str, Any]:
    res = store.residents.get(resident_id)
    if res is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Resident {resident_id} not found.")
    return res


def get_lease_or_404(lease_id: str) -> dict[str, Any]:
    lease = store.leases.get(lease_id)
    if lease is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Lease {lease_id} not found.")
    return lease


def get_notice_or_404(notice_id: str) -> dict[str, Any]:
    n = store.rent_notices.get(notice_id)
    if n is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"RentIncreaseNotice {notice_id} not found.")
    return n


def get_eviction_or_404(case_id: str) -> dict[str, Any]:
    c = store.eviction_cases.get(case_id)
    if c is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"EvictionCase {case_id} not found.")
    return c


def get_transfer_or_404(transfer_id: str) -> dict[str, Any]:
    t = store.home_sale_transfers.get(transfer_id)
    if t is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"HomeSaleTransfer {transfer_id} not found.")
    return t


def get_conversion_or_404(conv_id: str) -> dict[str, Any]:
    c = store.conversion_requests.get(conv_id)
    if c is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"ConversionRequest {conv_id} not found.")
    return c


# Existence checkers for body refs raise ERR_REFERENCED_RESOURCE_NOT_FOUND


def get_resident_body_or_404(resident_id: str) -> dict[str, Any]:
    res = store.residents.get(resident_id)
    if res is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", f"Resident {resident_id} not found.")
    return res


def get_lot_body_or_404(lot_id: str) -> dict[str, Any]:
    lot = store.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", f"Lot {lot_id} not found.")
    return lot


def get_home_body_or_404(home_id: str) -> dict[str, Any]:
    home = store.homes.get(home_id)
    if home is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", f"Home {home_id} not found.")
    return home


__all__ = [
    "init_common_fields",
    "init_bill_fields",
    "touch",
    "get_park_or_404",
    "get_lot_or_404",
    "get_home_or_404",
    "get_resident_or_404",
    "get_lease_or_404",
    "get_notice_or_404",
    "get_eviction_or_404",
    "get_transfer_or_404",
    "get_conversion_or_404",
    "get_resident_body_or_404",
    "get_lot_body_or_404",
    "get_home_body_or_404",
]
