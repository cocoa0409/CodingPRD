"""Payload factories — one per creatable resource, carrying input fields only.

Every factory takes keyword overrides so a test can vary exactly the field under
examination and leave the rest at a valid default. Server-generated and computed
fields are never part of a factory's output unless a test is deliberately proving
that the server ignores a client-supplied value.
"""

from typing import Any, Dict, List, Optional

from .types import (
    Disposition,
    FormulaVariant,
    MonitorPolicy,
    RecallClass,
    HoldScope,
    StorageClass,
    UrbanRural,
)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Program configuration
# ---------------------------------------------------------------------------

def service_area_payload(
    name: str = "North County",
    county_code: str = "NC01",
    poverty_population: int = 40000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "county_code": county_code,
            "poverty_population": poverty_population,
        },
        overrides,
    )


def service_area_payload_with_rurality(
    urban_rural: str = UrbanRural.URBAN, **overrides: Any
) -> Dict[str, Any]:
    payload = service_area_payload(**overrides)
    payload["urban_rural"] = urban_rural
    return payload


def agency_payload(
    service_area_id: str,
    name: str = "Alpha Food Bank",
    cold_storage_pallet_capacity: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "service_area_id": service_area_id,
            "cold_storage_pallet_capacity": cold_storage_pallet_capacity,
        },
        overrides,
    )


def commodity_payload(
    code: str = "BULK_RICE",
    name: str = "Bulk Rice",
    storage_class: str = StorageClass.DRY,
    net_weight_lbs_per_case: float = 20.0,
    cases_per_pallet: int = 50,
    entitlement_value_cents_per_case: int = 1200,
    shelf_life_days: int = 900,
    excess_case_ceiling: int = 500,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "code": code,
            "name": name,
            "storage_class": storage_class,
            "net_weight_lbs_per_case": net_weight_lbs_per_case,
            "cases_per_pallet": cases_per_pallet,
            "entitlement_value_cents_per_case": entitlement_value_cents_per_case,
            "shelf_life_days": shelf_life_days,
            "excess_case_ceiling": excess_case_ceiling,
        },
        overrides,
    )


def bulk_rice_payload(**overrides: Any) -> Dict[str, Any]:
    return commodity_payload(**overrides)


def frozen_chicken_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "code": "FROZEN_CHICKEN",
        "name": "Frozen Chicken",
        "storage_class": StorageClass.FROZEN,
        "net_weight_lbs_per_case": 30.125,
        "cases_per_pallet": 45,
        "entitlement_value_cents_per_case": 2600,
        "shelf_life_days": 365,
        "excess_case_ceiling": 400,
    }
    defaults.update(overrides)
    return commodity_payload(**defaults)


def canned_peaches_payload(**overrides: Any) -> Dict[str, Any]:
    """Per-case weight and pallet factor of the conversion example in the PRD."""
    defaults: Dict[str, Any] = {
        "code": "CANNED_PEACHES",
        "name": "Canned Peaches",
        "storage_class": StorageClass.DRY,
        "net_weight_lbs_per_case": 24.375,
        "cases_per_pallet": 60,
        "entitlement_value_cents_per_case": 900,
        "shelf_life_days": 730,
        "excess_case_ceiling": 500,
    }
    defaults.update(overrides)
    return commodity_payload(**defaults)


def warehouse_payload(
    name: str = "WH North",
    dock_count: int = 2,
    dry_pallet_capacity: int = 100,
    cold_pallet_capacity: int = 50,
    frozen_pallet_capacity: int = 20,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "dock_count": dock_count,
            "dry_pallet_capacity": dry_pallet_capacity,
            "cold_pallet_capacity": cold_pallet_capacity,
            "frozen_pallet_capacity": frozen_pallet_capacity,
        },
        overrides,
    )


def warehouse_payload_with_policy(
    monitor_policy: str = MonitorPolicy.SHELF_LIFE_BASED, **overrides: Any
) -> Dict[str, Any]:
    payload = warehouse_payload(**overrides)
    payload["monitor_policy"] = monitor_policy
    return payload


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def inventory_lot_payload(
    commodity_id: str,
    warehouse_id: str,
    federal_lot_code: str = "FL-0001",
    cases_received: int = 100,
    pack_date: str = "2026-05-01",
    best_by_date: str = "2026-11-01",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "commodity_id": commodity_id,
            "warehouse_id": warehouse_id,
            "federal_lot_code": federal_lot_code,
            "cases_received": cases_received,
            "pack_date": pack_date,
            "best_by_date": best_by_date,
        },
        overrides,
    )


def inventory_transfer_payload(
    from_lot_id: str,
    to_agency_id: str,
    cases: int,
    expected_inventory_lot_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "from_lot_id": from_lot_id,
            "to_agency_id": to_agency_id,
            "cases": cases,
            "expected_inventory_lot_version": expected_inventory_lot_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Eligibility paperwork
# ---------------------------------------------------------------------------

def civil_rights_training_payload(
    completed_at: str = "2026-07-01T00:00:00Z", attendee_count: int = 4, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"completed_at": completed_at, "attendee_count": attendee_count}, overrides
    )


def agreement_renewal_payload(
    agreement_start_date: str = "2026-07-01",
    agreement_end_date: str = "2027-06-30",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "agreement_start_date": agreement_start_date,
            "agreement_end_date": agreement_end_date,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Allocation cycle
# ---------------------------------------------------------------------------

def allocation_cycle_payload(
    offered_commodity_codes: Optional[List[str]] = None,
    cycle_code: str = "FY27Q1",
    formula_variant: str = FormulaVariant.STANDARD,
    allocatable_cases: int = 1000,
    admin_funds_pool_cents: int = 0,
    order_window_open_at: str = "2026-08-05T00:00:00Z",
    order_window_close_at: str = "2026-08-20T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "cycle_code": cycle_code,
            "formula_variant": formula_variant,
            "allocatable_cases": allocatable_cases,
            "admin_funds_pool_cents": admin_funds_pool_cents,
            "offered_commodity_codes": offered_commodity_codes or ["BULK_RICE"],
            "order_window_open_at": order_window_open_at,
            "order_window_close_at": order_window_close_at,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Orders, lines, appointments
# ---------------------------------------------------------------------------

def commodity_order_payload(
    cycle_id: str,
    agency_id: str,
    warehouse_id: str,
    expected_agency_allocation_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "cycle_id": cycle_id,
            "agency_id": agency_id,
            "warehouse_id": warehouse_id,
            "expected_agency_allocation_version": expected_agency_allocation_version,
        },
        overrides,
    )


def order_line_payload(commodity_id: str, cases_requested: int = 10, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"commodity_id": commodity_id, "cases_requested": cases_requested}, overrides
    )


def line_adjustments_payload(adjustments: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"line_adjustments": adjustments}


def line_adjustment(order_line_id: str, cases_approved: int) -> Dict[str, Any]:
    return {"order_line_id": order_line_id, "cases_approved": cases_approved}


def delivery_appointment_payload(
    order_id: str,
    dock_number: int = 1,
    window_start: str = "2026-08-10T10:00:00Z",
    window_end: str = "2026-08-10T12:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "order_id": order_id,
            "dock_number": dock_number,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def cancel_reason_payload(cancel_reason: str = "WITHDRAWN") -> Dict[str, Any]:
    return {"cancel_reason": cancel_reason}


def decline_reason_payload(decline_reason: str = "NO_DRY_SPACE") -> Dict[str, Any]:
    return {"decline_reason": decline_reason}


def void_reason_payload(void_reason: str = "DATA_ENTRY_ERROR") -> Dict[str, Any]:
    return {"void_reason": void_reason}


# ---------------------------------------------------------------------------
# Recalls
# ---------------------------------------------------------------------------

def recall_payload(
    source_lot_id: str,
    recall_class: str = RecallClass.CLASS_II,
    hold_scope: str = HoldScope.LOT_ONLY,
    reason: str = "Supplier notified a possible foreign-material contamination.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "source_lot_id": source_lot_id,
            "recall_class": recall_class,
            "hold_scope": hold_scope,
            "reason": reason,
        },
        overrides,
    )


def recall_expansion_payload(agency_id: str) -> Dict[str, Any]:
    return {"agency_id": agency_id}


def disposition_payload(
    disposition: str = Disposition.DESTROYED, cases_accounted: int = 0, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"disposition": disposition, "cases_accounted": cases_accounted}, overrides
    )


# ---------------------------------------------------------------------------
# Household distributions
# ---------------------------------------------------------------------------

def household_distribution_payload(
    agency_id: str,
    cycle_id: str,
    commodity_id: str,
    household_size: int = 3,
    declared_monthly_income_cents: int = 330000,
    cases_distributed: int = 2,
    self_declaration_signed: bool = True,
    distribution_date: str = "2026-08-10",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "agency_id": agency_id,
            "cycle_id": cycle_id,
            "commodity_id": commodity_id,
            "household_size": household_size,
            "declared_monthly_income_cents": declared_monthly_income_cents,
            "self_declaration_signed": self_declaration_signed,
            "cases_distributed": cases_distributed,
            "distribution_date": distribution_date,
        },
        overrides,
    )
