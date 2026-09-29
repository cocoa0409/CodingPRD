"""Request-payload builders.

Each builder returns a complete, valid payload for one endpoint and accepts
keyword overrides, so a test states only the fields its scenario turns on.
"""

from typing import Any, Dict, List, Optional

# ─── Canonical scenario values ────────────────────────────────────────────────
DEFAULT_CLOCK = "2026-09-01T08:00:00Z"

FACTORY_NAME = "Puget Modular Plant 1"
FACTORY_CODE = "PMP1"
FACTORY_TAKT_MINUTES = 90
FACTORY_STATION_COUNT = 6
FACTORY_PARALLEL_CAPACITY = 2
FACTORY_WIP_UNIT_VALUE_CENTS = 8750000

AGENCY_NAME = "Cascade Inspection Services"
AGENCY_CODE = "CIS"
AGENCY_STATE_CODES = ["WA"]
AGENCY_FEE_CENTS = 120000

PROJECT_NAME = "Rainier Flats"
PROJECT_STATE_CODE = "WA"
PROJECT_AHJ_CODE = "SEA"
PROJECT_PLANNED_MODULE_COUNT = 4
PROJECT_CONTRACT_PRICE_CENTS = 3200000000
CRANE_CHART = [
    {"radius_ft": 60, "capacity_lb": 150000},
    {"radius_ft": 90, "capacity_lb": 96000},
    {"radius_ft": 120, "capacity_lb": 60000},
]

MODULE_WIDTH_IN = 180
MODULE_LENGTH_IN = 600
MODULE_HEIGHT_IN = 156
MODULE_GROSS_WEIGHT_LB = 76600

CARRIER_CODE = "NWHEAVY"
PLANNED_DEPARTURE_AT = "2026-09-08T13:00:00Z"
PLANNED_ARRIVAL_AT = "2026-09-08T21:00:00Z"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose value is ``...``.

    ``...`` is the suite's "omit this field" sentinel. It must be honoured for
    values that reached ``base`` through an explicitly-named factory parameter
    (e.g. ``module_payload(set_sequence_index=...)``) exactly as it is for keys
    arriving via ``**overrides`` — otherwise the Ellipsis is serialised into the
    request body and the client raises a TypeError instead of the caller getting
    the field-absent payload it asked for.
    """
    merged = dict(base)
    for key, value in overrides.items():
        if value is ...:
            merged.pop(key, None)
        else:
            merged[key] = value
    return {key: value for key, value in merged.items() if value is not ...}


# ─── Clock ────────────────────────────────────────────────────────────────────
def clock_payload(current_utc: str = DEFAULT_CLOCK, **overrides) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# ─── Factory ──────────────────────────────────────────────────────────────────
def factory_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": FACTORY_NAME,
            "code": FACTORY_CODE,
            "takt_minutes": FACTORY_TAKT_MINUTES,
            "station_count": FACTORY_STATION_COUNT,
            "parallel_station_capacity": FACTORY_PARALLEL_CAPACITY,
            "wip_unit_value_cents": FACTORY_WIP_UNIT_VALUE_CENTS,
        },
        overrides,
    )


def line_state_payload(line_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"line_state": line_state}, overrides)


# ─── Inspection agency ────────────────────────────────────────────────────────
def agency_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": AGENCY_NAME,
            "agency_code": AGENCY_CODE,
            "accredited_state_codes": list(AGENCY_STATE_CODES),
            "per_inspection_fee_cents": AGENCY_FEE_CENTS,
        },
        overrides,
    )


def accreditation_payload(accreditation_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"accreditation_state": accreditation_state}, overrides)


# ─── Project ──────────────────────────────────────────────────────────────────
def project_payload(factory_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": PROJECT_NAME,
            "factory_id": factory_id,
            "state_code": PROJECT_STATE_CODE,
            "ahj_code": PROJECT_AHJ_CODE,
            "planned_module_count": PROJECT_PLANNED_MODULE_COUNT,
            "contract_price_cents": PROJECT_CONTRACT_PRICE_CENTS,
            "crane_capacity_chart": [dict(entry) for entry in CRANE_CHART],
        },
        overrides,
    )


def weather_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"forecast_precip_probability_pct": 0, "forecast_wind_gust_mph": 0}, overrides
    )


# ─── Design package ───────────────────────────────────────────────────────────
def design_package_payload(
    project_id: str, expected_project_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "revision_index": 1,
            "module_split_count": PROJECT_PLANNED_MODULE_COUNT,
            "expected_project_version": expected_project_version,
            "connection_detail_state": "COMPLETE",
        },
        overrides,
    )


def submit_payload(**overrides) -> Dict[str, Any]:
    return _merge({"review_note": "R1"}, overrides)


def review_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ─── Module ───────────────────────────────────────────────────────────────────
def module_payload(
    project_id: str,
    design_package_id: str,
    module_code: str = "M-01",
    set_sequence_index: int = 1,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "design_package_id": design_package_id,
            "module_code": module_code,
            "set_sequence_index": set_sequence_index,
            "width_in": MODULE_WIDTH_IN,
            "length_in": MODULE_LENGTH_IN,
            "height_in": MODULE_HEIGHT_IN,
            "gross_weight_lb": MODULE_GROSS_WEIGHT_LB,
        },
        overrides,
    )


def line_slot_payload(line_slot_start: str, **overrides) -> Dict[str, Any]:
    return _merge({"line_slot_start": line_slot_start}, overrides)


def advance_payload(stations_advanced: int = 1, **overrides) -> Dict[str, Any]:
    return _merge({"stations_advanced": stations_advanced}, overrides)


def pick_payload(
    pick_window_start: str,
    pick_window_end: str,
    pick_radius_ft: int = 75,
    rigging_weight_lb: int = 4000,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "pick_window_start": pick_window_start,
            "pick_window_end": pick_window_end,
            "pick_radius_ft": pick_radius_ft,
            "rigging_weight_lb": rigging_weight_lb,
        },
        overrides,
    )


def close_connections_payload(
    field_scope_signed_off: bool = True, **overrides
) -> Dict[str, Any]:
    return _merge({"field_scope_signed_off": field_scope_signed_off}, overrides)


# ─── Permit record ────────────────────────────────────────────────────────────
def permit_payload(
    project_id: str,
    track: str = "STATE_MODULAR_PROGRAM",
    scope: str = "PLAN_REVIEW",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {"project_id": project_id, "track": track, "scope": scope}, overrides
    )


def permit_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ─── Inspection record ────────────────────────────────────────────────────────
def inspection_payload(
    module_id: str, agency_id: str, stage: str = "IN_PLANT", **overrides
) -> Dict[str, Any]:
    return _merge(
        {"module_id": module_id, "agency_id": agency_id, "stage": stage}, overrides
    )


def inspection_result_payload(
    result: str, defect_count: int = 0, severity_max: int = 0, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "result": result,
            "defect_count": defect_count,
            "severity_max": severity_max,
        },
        overrides,
    )


def clear_hold_payload(
    corrective_note: str = "corrective work complete", **overrides
) -> Dict[str, Any]:
    return _merge({"corrective_note": corrective_note}, overrides)


# ─── Shipment ─────────────────────────────────────────────────────────────────
def shipment_payload(
    project_id: str, route_state_codes: Optional[List[str]] = None, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "carrier_code": CARRIER_CODE,
            "route_state_codes": list(route_state_codes or ["WA"]),
            "planned_departure_at": PLANNED_DEPARTURE_AT,
            "planned_arrival_at": PLANNED_ARRIVAL_AT,
        },
        overrides,
    )


def load_module_payload(
    module_id: str, expected_shipment_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "module_id": module_id,
            "expected_shipment_version": expected_shipment_version,
        },
        overrides,
    )


def route_survey_payload(
    survey_completed_at: str = "2026-09-01T09:00:00Z",
    permit_expires_at: str = "2026-09-20T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "survey_completed_at": survey_completed_at,
            "permit_expires_at": permit_expires_at,
        },
        overrides,
    )


def cancel_payload(reason: str = "carrier double-booked", **overrides) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ─── Defect claim ─────────────────────────────────────────────────────────────
def defect_claim_payload(
    module_id: str,
    discovered_phase: str = "FACTORY",
    repair_cost_cents: int = 1234567,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "module_id": module_id,
            "discovered_phase": discovered_phase,
            "description": "sheathing gap",
            "repair_cost_cents": repair_cost_cents,
        },
        overrides,
    )


def adjudicate_payload(**overrides) -> Dict[str, Any]:
    return _merge({"adjudication_note": "allocation recorded"}, overrides)


def dispute_payload(
    dispute_note: str = "the factory disputes the allocation", **overrides
) -> Dict[str, Any]:
    return _merge({"dispute_note": dispute_note}, overrides)


# ─── Draw request ─────────────────────────────────────────────────────────────
def draw_request_payload(
    project_id: str,
    certifying_agency_id: str,
    basis_mode: str = "WIP_DEPOSIT",
    draw_index: int = 1,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "draw_index": draw_index,
            "basis_mode": basis_mode,
            "certifying_agency_id": certifying_agency_id,
        },
        overrides,
    )


def certify_payload(**overrides) -> Dict[str, Any]:
    return _merge({"certification_note": "basis certified"}, overrides)


def reject_payload(
    reject_reason: str = "documentation incomplete", **overrides
) -> Dict[str, Any]:
    return _merge({"reject_reason": reject_reason}, overrides)
