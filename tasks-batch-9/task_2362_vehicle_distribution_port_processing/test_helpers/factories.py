"""Request-payload builders.

Each builder returns the minimum valid body for one write operation, with the
optional fields omitted unless a caller supplies them, so that a test which
cares about a declared default can simply not pass it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .constants import (
    CENTER_DAILY_STORAGE_RATE_CENTS,
    CENTER_FUEL_SURCHARGE_PCT,
    CENTER_LABOR_RATE_CENTS_PER_HOUR,
    CENTER_NAME,
    CENTER_PORT_CODE,
    CENTER_YARD_CAPACITY_SLOTS,
    DAMAGE_ZONE_BODY_PANEL,
    HOLD_SCOPE_MODEL_LINE,
    HOLD_SCOPE_SINGLE_VIN,
    HOLD_TYPE_RECALL,
    MODEL_LINE_LX500,
    OUTCOME_FAIL,
    OUTCOME_PASS,
    RESPONSE_ACCEPT,
    RESPONSE_DENY,
    RESPONSE_DISPUTE,
    ROUTE_ZONE_A,
    DECISION_AUTHORIZE,
    DECISION_REJECT,
)

_OMIT = object()


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the keys whose value is the omission sentinel."""
    return {k: v for k, v in payload.items() if v is not _OMIT}


# --------------------------------------------------------------------------
# processing center / berth / vessel
# --------------------------------------------------------------------------
def center_payload(
    *,
    name: Any = CENTER_NAME,
    port_code: Any = CENTER_PORT_CODE,
    yard_capacity_slots: Any = CENTER_YARD_CAPACITY_SLOTS,
    daily_storage_rate_cents: Any = CENTER_DAILY_STORAGE_RATE_CENTS,
    labor_rate_cents_per_hour: Any = CENTER_LABOR_RATE_CENTS_PER_HOUR,
    fuel_surcharge_pct: Any = CENTER_FUEL_SURCHARGE_PCT,
    free_storage_days: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "name": name,
            "port_code": port_code,
            "yard_capacity_slots": yard_capacity_slots,
            "daily_storage_rate_cents": daily_storage_rate_cents,
            "labor_rate_cents_per_hour": labor_rate_cents_per_hour,
            "fuel_surcharge_pct": fuel_surcharge_pct,
            "free_storage_days": free_storage_days,
        }
    )


def berth_payload(
    processing_center_id: str,
    *,
    berth_code: Any = "B1",
    turnaround_buffer_minutes: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "processing_center_id": processing_center_id,
            "berth_code": berth_code,
            "turnaround_buffer_minutes": turnaround_buffer_minutes,
        }
    )


def vessel_payload(
    processing_center_id: str,
    berth_id: str,
    *,
    voyage_code: Any = "V001",
    carrier_scac: Any = "OCNL",
    berth_window_start: Any = "2026-08-01T06:00:00Z",
    berth_window_end: Any = "2026-08-01T18:00:00Z",
    declared_unit_count: Any = 10,
) -> Dict[str, Any]:
    return _prune(
        {
            "processing_center_id": processing_center_id,
            "berth_id": berth_id,
            "voyage_code": voyage_code,
            "carrier_scac": carrier_scac,
            "berth_window_start": berth_window_start,
            "berth_window_end": berth_window_end,
            "declared_unit_count": declared_unit_count,
        }
    )


def vehicle_payload(
    vin_value: str,
    *,
    model_line: Any = MODEL_LINE_LX500,
    pio_program_code: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "vin": vin_value,
            "model_line": model_line,
            "pio_program_code": pio_program_code,
        }
    )


# --------------------------------------------------------------------------
# damage survey / claim
# --------------------------------------------------------------------------
def damage_line(
    damage_zone: str = DAMAGE_ZONE_BODY_PANEL,
    severity_points: Any = 25,
    repair_estimate_cents: Any = 40_000,
) -> Dict[str, Any]:
    return {
        "damage_zone": damage_zone,
        "severity_points": severity_points,
        "repair_estimate_cents": repair_estimate_cents,
    }


def survey_payload(line_items: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = list(line_items) if line_items is not None else [damage_line()]
    return {"line_items": items}


def claim_payload(expected_damage_survey_version: Any, *, carrier_scac: Any = "OCNL") -> Dict[str, Any]:
    return {
        "carrier_scac": carrier_scac,
        "expected_damage_survey_version": expected_damage_survey_version,
    }


def accept_payload() -> Dict[str, Any]:
    return {"outcome": RESPONSE_ACCEPT}


def dispute_payload(disputed_amount_cents: Any) -> Dict[str, Any]:
    return {"outcome": RESPONSE_DISPUTE, "disputed_amount_cents": disputed_amount_cents}


def deny_payload() -> Dict[str, Any]:
    return {"outcome": RESPONSE_DENY}


def resubmit_payload(revised_claim_amount_cents: Any) -> Dict[str, Any]:
    return {"revised_claim_amount_cents": revised_claim_amount_cents}


def settle_payload(settled_amount_cents: Any) -> Dict[str, Any]:
    return {"settled_amount_cents": settled_amount_cents}


# --------------------------------------------------------------------------
# repair orders
# --------------------------------------------------------------------------
def repair_order_payload(
    estimate_cents: Any,
    *,
    description: Any = "Bumper refinish",
    carrier_claim_id: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "description": description,
            "estimate_cents": estimate_cents,
            "carrier_claim_id": carrier_claim_id,
        }
    )


def authorize_payload() -> Dict[str, Any]:
    return {"decision": DECISION_AUTHORIZE}


def reject_payload() -> Dict[str, Any]:
    return {"decision": DECISION_REJECT}


def repair_complete_payload(actual_cost_cents: Any) -> Dict[str, Any]:
    return {"actual_cost_cents": actual_cost_cents}


# --------------------------------------------------------------------------
# accessory kits and work orders
# --------------------------------------------------------------------------
def kit_payload(
    *,
    kit_code: Any = "K-ALLOY",
    program_code: Any = "PIO-A",
    received_qty_total: Any = 10,
    unit_cost_cents: Any = 24_000,
    install_minutes_per_unit: Any = 45,
) -> Dict[str, Any]:
    return _prune(
        {
            "kit_code": kit_code,
            "program_code": program_code,
            "received_qty_total": received_qty_total,
            "unit_cost_cents": unit_cost_cents,
            "install_minutes_per_unit": install_minutes_per_unit,
        }
    )


def work_order_payload(accessory_kit_id: str, *, qty: Any = 1) -> Dict[str, Any]:
    return {"accessory_kit_id": accessory_kit_id, "qty": qty}


# --------------------------------------------------------------------------
# quality inspections
# --------------------------------------------------------------------------
def pass_payload(defect_count: Any = 0) -> Dict[str, Any]:
    return {"outcome": OUTCOME_PASS, "defect_count": defect_count}


def fail_payload(defect_count: Any = 1) -> Dict[str, Any]:
    return {"outcome": OUTCOME_FAIL, "defect_count": defect_count}


# --------------------------------------------------------------------------
# hold orders
# --------------------------------------------------------------------------
def model_line_hold_payload(
    model_line: Any,
    *,
    hold_type: Any = HOLD_TYPE_RECALL,
    reference_code: Any = "RC-2026-01",
) -> Dict[str, Any]:
    return {
        "hold_type": hold_type,
        "scope_type": HOLD_SCOPE_MODEL_LINE,
        "reference_code": reference_code,
        "model_line": model_line,
    }


def single_vin_hold_payload(
    vehicle_id: Any,
    *,
    hold_type: Any = HOLD_TYPE_RECALL,
    reference_code: Any = "RC-2026-02",
) -> Dict[str, Any]:
    return {
        "hold_type": hold_type,
        "scope_type": HOLD_SCOPE_SINGLE_VIN,
        "reference_code": reference_code,
        "vehicle_id": vehicle_id,
    }


# --------------------------------------------------------------------------
# dealers, carriers, allocation
# --------------------------------------------------------------------------
def dealer_payload(
    *,
    dealer_code: Any = "D-MAIN",
    name: Any = "Harbor Motors",
    route_zone: Any = ROUTE_ZONE_A,
    distance_miles: Any = 100,
    allocation_quota: Any = 5,
) -> Dict[str, Any]:
    return _prune(
        {
            "dealer_code": dealer_code,
            "name": name,
            "route_zone": route_zone,
            "distance_miles": distance_miles,
            "allocation_quota": allocation_quota,
        }
    )


def carrier_payload(
    *,
    carrier_code: Any = "TC-ROAD",
    name: Any = "Roadway Haulers",
    served_route_zones: Any = ("A", "B", "C"),
    linehaul_rate_cents_per_mile: Any = 412,
    slot_capacity: Any = 4,
    concurrent_load_capacity: Any = 2,
    status: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "carrier_code": carrier_code,
            "name": name,
            "served_route_zones": list(served_route_zones)
            if isinstance(served_route_zones, (list, tuple))
            else served_route_zones,
            "linehaul_rate_cents_per_mile": linehaul_rate_cents_per_mile,
            "slot_capacity": slot_capacity,
            "concurrent_load_capacity": concurrent_load_capacity,
            "status": status,
        }
    )


def allocation_payload(
    dealer_id: str,
    expected_vehicle_version: Any,
    *,
    pickup_window_start: Any = "2026-08-03T08:00:00Z",
    pickup_window_end: Any = "2026-08-03T12:00:00Z",
) -> Dict[str, Any]:
    return {
        "dealer_id": dealer_id,
        "pickup_window_start": pickup_window_start,
        "pickup_window_end": pickup_window_end,
        "expected_vehicle_version": expected_vehicle_version,
    }
