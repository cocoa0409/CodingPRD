"""Payload factories - request bodies only, built from PRD-declared input fields.

Numeric money/mass/area values are plain JSON numbers (never strings); every
factory accepts **overrides so a test can vary exactly the field under test.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    BINDER_FORMALDEHYDE_FREE,
    BINDER_PHENOLIC,
    PLANT_NEWARK,
    PROGRAM_LOT_MEAN,
    PROGRAM_NO_DERATE,
    PROGRAM_PER_SPECIMEN,
    ZONE_SETPOINTS_4,
)

_counter = {"n": 0}


def _next(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:04d}"


# --- Certification programs ---------------------------------------------------


def certification_program_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(PROGRAM_PER_SPECIMEN)
    payload["code"] = _next("RCERT")
    payload.update(overrides)
    return payload


def per_specimen_program_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(PROGRAM_PER_SPECIMEN)
    payload.update(overrides)
    return payload


def lot_mean_program_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(PROGRAM_LOT_MEAN)
    payload.update(overrides)
    return payload


def no_derate_program_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(PROGRAM_NO_DERATE)
    payload.update(overrides)
    return payload


# --- Plants -------------------------------------------------------------------


def plant_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(PLANT_NEWARK)
    payload.update(overrides)
    return payload


def emissions_report_payload(
    period_start: str, period_end: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload


def posture_review_payload(
    decision: str, override_reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if override_reason is not None:
        payload["override_reason"] = override_reason
    payload.update(overrides)
    return payload


# --- Binder formulations ------------------------------------------------------


def binder_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(BINDER_PHENOLIC)
    payload["code"] = _next("BF")
    payload.update(overrides)
    return payload


def formaldehyde_free_binder_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(BINDER_FORMALDEHYDE_FREE)
    payload.update(overrides)
    return payload


def phenolic_binder_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(BINDER_PHENOLIC)
    payload.update(overrides)
    return payload


def binder_emissions_test_payload(
    formaldehyde_ppm: float, voc_g_per_kg: float, lab_reference: str = "LAB-REF-1"
) -> Dict[str, Any]:
    return {
        "formaldehyde_ppm": formaldehyde_ppm,
        "voc_g_per_kg": voc_g_per_kg,
        "lab_reference": lab_reference,
    }


def binder_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def binder_revise_payload(decision: str = "REVISE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# --- Product lines ------------------------------------------------------------


def product_line_payload(
    plant_id: str,
    binder_formulation_id: str,
    certification_program_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sku": _next("SKU"),
        "plant_id": plant_id,
        "binder_formulation_id": binder_formulation_id,
        "certification_program_id": certification_program_id,
        "form": "BATT",
        "density_pcf": 0.90,
        "facing_type": "UNFACED",
        "width_in": 15.0,
        "thickness_in": 3.5,
        "declared_r_value": 13.0,
        "bag_sqft": 88.0,
        "bale_volume_ft3": 21.0,
        "bale_mass_kg": 12.5,
        "compression_ratio": 6.0,
        "mass_rate_kg_per_min": 34.5,
    }
    payload.update(overrides)
    return payload


def packaging_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


def sku_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# --- Production runs ----------------------------------------------------------


def production_run_payload(
    plant_id: str,
    product_line_id: str,
    scheduled_start: str = "2026-08-02T06:00:00Z",
    scheduled_end: str = "2026-08-02T14:00:00Z",
    line_index: int = 1,
    target_pull_kg: float = 9200.0,
    zone_setpoints_f: Optional[List[float]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plant_id": plant_id,
        "product_line_id": product_line_id,
        "line_index": line_index,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "target_pull_kg": target_pull_kg,
        "zone_setpoints_f": list(
            zone_setpoints_f if zone_setpoints_f is not None else ZONE_SETPOINTS_4
        ),
    }
    payload.update(overrides)
    return payload


def start_cure_payload(
    avg_zone_temp_f: float = 490.0,
    line_speed_fpm: float = 36.0,
    binder_applied_kg: float = 400.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "avg_zone_temp_f": avg_zone_temp_f,
        "line_speed_fpm": line_speed_fpm,
        "binder_applied_kg": binder_applied_kg,
    }
    payload.update(overrides)
    return payload


# --- Changeover events --------------------------------------------------------


def changeover_payload(
    plant_id: str,
    outgoing_run_id: str,
    incoming_run_id: str,
    line_index: int,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plant_id": plant_id,
        "outgoing_run_id": outgoing_run_id,
        "incoming_run_id": incoming_run_id,
        "line_index": line_index,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def close_changeover_payload(
    weighed_trim_kg: float, recovered_cullet_kg: float, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "weighed_trim_kg": weighed_trim_kg,
        "recovered_cullet_kg": recovered_cullet_kg,
    }
    payload.update(overrides)
    return payload


# --- Thermal tests ------------------------------------------------------------


def thermal_test_payload(
    production_run_id: str,
    product_line_id: str,
    certification_program_id: str,
    window_start: str = "2026-08-03T08:00:00Z",
    window_end: str = "2026-08-03T16:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "production_run_id": production_run_id,
        "product_line_id": product_line_id,
        "certification_program_id": certification_program_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def retest_window_payload(window_start: str, window_end: str) -> Dict[str, Any]:
    return {"window_start": window_start, "window_end": window_end}


# --- Inventory lots -----------------------------------------------------------


def quarantine_payload(
    disposition: str,
    weighed_scrap_lb: Optional[float] = None,
    quarantine_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    if weighed_scrap_lb is not None:
        payload["weighed_scrap_lb"] = weighed_scrap_lb
    if quarantine_note is not None:
        payload["quarantine_note"] = quarantine_note
    payload.update(overrides)
    return payload


# --- Cullet batches -----------------------------------------------------------


def cullet_batch_payload(
    plant_id: str,
    mass_kg: float,
    expected_plant_version: int,
    source_type: str = "EXTERNAL",
    source_run_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plant_id": plant_id,
        "source_type": source_type,
        "mass_kg": mass_kg,
        "expected_plant_version": expected_plant_version,
    }
    if source_run_id is not None:
        payload["source_run_id"] = source_run_id
    payload.update(overrides)
    return payload


# --- Allocation cycles --------------------------------------------------------


def allocation_cycle_payload(
    plant_id: str,
    product_line_id: str,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-08-31T00:00:00Z",
    allocation_basis: str = "CONTRACT_FIRST",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plant_id": plant_id,
        "product_line_id": product_line_id,
        "period_start": period_start,
        "period_end": period_end,
        "allocation_basis": allocation_basis,
    }
    payload.update(overrides)
    return payload


# --- Channel orders -----------------------------------------------------------


def channel_order_payload(
    product_line_id: str,
    requested_sqft: float,
    channel_type: str = "DISTRIBUTOR",
    priority_tier: str = "CONTRACT",
    required_by: str = "2026-08-20T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_line_id": product_line_id,
        "channel_type": channel_type,
        "priority_tier": priority_tier,
        "requested_sqft": requested_sqft,
        "required_by": required_by,
    }
    payload.update(overrides)
    return payload


# --- Allocation lines ---------------------------------------------------------


def allocation_line_payload(
    allocation_cycle_id: str,
    channel_order_id: str,
    inventory_lot_id: str,
    allocated_sqft: float,
    expected_allocation_cycle_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "allocation_cycle_id": allocation_cycle_id,
        "channel_order_id": channel_order_id,
        "inventory_lot_id": inventory_lot_id,
        "allocated_sqft": allocated_sqft,
        "expected_allocation_cycle_version": expected_allocation_cycle_version,
    }
    payload.update(overrides)
    return payload
