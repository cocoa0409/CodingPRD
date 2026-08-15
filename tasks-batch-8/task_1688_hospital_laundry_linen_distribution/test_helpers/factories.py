"""Payload factories — one per creatable resource, input fields only."""
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def create_facility_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": TEST_DEFAULTS["FACILITY_NAME"],
        "rate_per_lb_cents": TEST_DEFAULTS["RATE_PER_LB_CENTS"],
        "isolation_surcharge_pct": TEST_DEFAULTS["ISOLATION_SURCHARGE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "facility_id": facility_id,
        "name": "ICU",
        "unit_tier": "CRITICAL",
    }
    defaults.update(overrides)
    return defaults


def create_linen_stock_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "facility_id": facility_id,
        "sku": TEST_DEFAULTS["SHEET_SKU"],
        "display_name": TEST_DEFAULTS["SHEET_NAME"],
        "category": "FLATWORK",
        "piece_weight_lbs": TEST_DEFAULTS["SHEET_WEIGHT_LBS"],
        "unit_cost_cents": TEST_DEFAULTS["SHEET_UNIT_COST_CENTS"],
        "max_wash_cycles": TEST_DEFAULTS["SHEET_MAX_WASH_CYCLES"],
        "reorder_point_pieces": TEST_DEFAULTS["SHEET_REORDER_POINT"],
        "opening_pieces": TEST_DEFAULTS["SHEET_OPENING_PIECES"],
        "opening_reserve_pieces": TEST_DEFAULTS["SHEET_OPENING_RESERVE"],
    }
    defaults.update(overrides)
    return defaults


def create_par_level_payload(
    unit_id: str, stock_id: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "unit_id": unit_id,
        "stock_id": stock_id,
        "base_par_quantity": 20,
        "cart_cycle": "DAILY",
    }
    defaults.update(overrides)
    return defaults


def update_par_level_payload(
    expected_par_level_version: int, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "expected_par_level_version": expected_par_level_version,
    }
    defaults.update(overrides)
    return defaults


def create_cart_run_payload(unit_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "unit_id": unit_id,
        "scheduled_start": "2026-08-02T08:00:00Z",
        "scheduled_end": "2026-08-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_cart_run_payload(
    soiled_lines: Optional[List[Dict[str, Any]]] = None, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "soiled_lines": soiled_lines if soiled_lines is not None else [],
        "storage_attested": True,
    }
    defaults.update(overrides)
    return defaults


def recount_cart_run_payload(
    corrected_soiled_lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {"corrected_soiled_lines": corrected_soiled_lines}


def create_soiled_manifest_payload(
    facility_id: str,
    cart_run_ids: List[str],
    lines: List[Dict[str, Any]],
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "facility_id": facility_id,
        "cart_run_ids": cart_run_ids,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def return_manifest_payload(
    returned_lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {"returned_lines": returned_lines}


def create_invoice_payload(
    facility_id: str, manifest_ids: List[str], **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "facility_id": facility_id,
        "manifest_ids": manifest_ids,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-07T00:00:00Z",
        "period_adjusted_patient_days": 50,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(
    unit_id: str, manifest_id: str, stock_id: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "unit_id": unit_id,
        "manifest_id": manifest_id,
        "stock_id": stock_id,
        "complaint_type": "STAINS",
        "pieces_affected": 1,
    }
    defaults.update(overrides)
    return defaults


def create_surge_event_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "facility_id": facility_id,
        "severity": "LEVEL_1",
        "par_multiplier": 1.5,
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-08-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def stock_adjustment_payload(
    delta_pieces: int, expected_linen_stock_version: int, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "delta_pieces": delta_pieces,
        "reason": "FOUND",
        "expected_linen_stock_version": expected_linen_stock_version,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
