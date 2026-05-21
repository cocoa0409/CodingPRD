"""Serialization helpers — turn internal entity dicts into API JSON shapes."""
from __future__ import annotations

from typing import Any

from ..clock import format_timestamp


def _dt_field(value):
    """Normalise stored datetime-ish field to ISO string (or pass through if already str)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return format_timestamp(value)


def serialize_park(park: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": park["id"],
        "name": park["name"],
        "state_code": park["state_code"],
        "master_cpi_pct": park["master_cpi_pct"],
        "utility_apportionment_method": park["utility_apportionment_method"],
        "billing_period_anchor_day": park["billing_period_anchor_day"],
        "ownership_pool_count": park["ownership_pool_count"],
        "created_at": park["created_at"],
        "updated_at": park["updated_at"],
        "version": park["version"],
    }


def serialize_lot(lot: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": lot["id"],
        "park_id": lot["park_id"],
        "lot_number": lot["lot_number"],
        "ownership_mode": lot["ownership_mode"],
        "base_rent_cents": lot["base_rent_cents"],
        "sub_meter_reading_kwh": lot["sub_meter_reading_kwh"],
        "home_id": lot.get("home_id"),
        "current_lease_id": lot.get("current_lease_id"),
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def serialize_home(home: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": home["id"],
        "park_id": home["park_id"],
        "lot_id": home.get("lot_id"),
        "owner_resident_id": home.get("owner_resident_id"),
        "vin": home["vin"],
        "assessed_value_cents": home["assessed_value_cents"],
        "created_at": home["created_at"],
        "updated_at": home["updated_at"],
        "version": home["version"],
    }


def serialize_resident(resident: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": resident["id"],
        "full_name": resident["full_name"],
        "email": resident["email"],
        "violation_count_12mo": resident["violation_count_12mo"],
        "created_at": resident["created_at"],
        "updated_at": resident["updated_at"],
        "version": resident["version"],
    }


def serialize_lease(lease: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": lease["id"],
        "lot_id": lease["lot_id"],
        "resident_id": lease["resident_id"],
        "monthly_rent_cents": lease.get("monthly_rent_cents"),
        "start_date": _dt_field(lease.get("start_date")),
        "status": lease["status"],
        "outstanding_balance_cents": lease["outstanding_balance_cents"],
        "predecessor_lease_id": lease.get("predecessor_lease_id"),
        "created_at": lease["created_at"],
        "updated_at": lease["updated_at"],
        "version": lease["version"],
    }


def serialize_notice(notice: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": notice["id"],
        "lease_id": notice["lease_id"],
        "proposed_new_rent_cents": notice["proposed_new_rent_cents"],
        "effective_on": _dt_field(notice.get("effective_on")),
        "capped_new_rent_cents": notice.get("capped_new_rent_cents"),
        "status": notice["status"],
        "created_at": notice["created_at"],
        "updated_at": notice["updated_at"],
        "version": notice["version"],
    }


def serialize_eviction(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case["id"],
        "lease_id": case["lease_id"],
        "violation_type": case["violation_type"],
        "filed_at": _dt_field(case.get("filed_at")),
        "cure_deadline": _dt_field(case.get("cure_deadline")),
        "status": case["status"],
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
        "version": case["version"],
    }


def serialize_utility_bill(bill: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": bill["id"],
        "lot_id": bill["lot_id"],
        "lease_id": bill.get("lease_id"),
        "billing_period_start": _dt_field(bill.get("billing_period_start")),
        "billing_period_end": _dt_field(bill.get("billing_period_end")),
        "master_total_cents": bill["master_total_cents"],
        "lot_share_cents": bill["lot_share_cents"],
        "rent_due_cents": bill["rent_due_cents"],
        "total_due_cents": bill["total_due_cents"],
        "paid_at": _dt_field(bill.get("paid_at")),
        "created_at": bill["created_at"],
    }


def serialize_transfer(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": t["id"],
        "home_id": t["home_id"],
        "seller_resident_id": t["seller_resident_id"],
        "buyer_resident_id": t["buyer_resident_id"],
        "sale_price_cents": t["sale_price_cents"],
        "status": t["status"],
        "new_lease_id": t.get("new_lease_id"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_conversion(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c["id"],
        "lot_id": c["lot_id"],
        "prospective_buyer_resident_id": c["prospective_buyer_resident_id"],
        "offer_price_cents": c["offer_price_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


__all__ = [
    "serialize_park",
    "serialize_lot",
    "serialize_home",
    "serialize_resident",
    "serialize_lease",
    "serialize_notice",
    "serialize_eviction",
    "serialize_utility_bill",
    "serialize_transfer",
    "serialize_conversion",
]
