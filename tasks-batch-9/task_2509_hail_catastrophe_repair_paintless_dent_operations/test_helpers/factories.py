"""Payload factories — one per resource, client-supplied input fields only.

Server-minted values (identifiers, audit fields, derived money, derived
counters, statuses) never appear here; the PRD says the server maintains them.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_FACILITY,
    DEFAULT_INSURER,
    DEFAULT_JURISDICTION,
    DEFAULT_RATE_AGREEMENT,
    DEFAULT_STORM_EVENT,
    DEFAULT_VEHICLE,
    DEPLOYMENT_END,
    DEPLOYMENT_START,
    PERMIT_WINDOW_FROM,
    PERMIT_WINDOW_TO,
)


def _merged(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    return payload


# ─── Storm events ─────────────────────────────────────────────────────────────

def storm_event_payload(**overrides) -> Dict[str, Any]:
    return _merged(DEFAULT_STORM_EVENT, overrides)


def storm_event_decision_payload(decision: str = "TARGET") -> Dict[str, Any]:
    return {"decision": decision}


# ─── Facilities ───────────────────────────────────────────────────────────────

def facility_payload(storm_event_id: str, **overrides) -> Dict[str, Any]:
    return _merged({"storm_event_id": storm_event_id, **DEFAULT_FACILITY}, overrides)


# ─── Permits ──────────────────────────────────────────────────────────────────

def permit_payload(
    facility_id: str,
    permit_type: str = "TEMP_BUSINESS_LICENSE",
    issuing_jurisdiction: str = DEFAULT_JURISDICTION,
    **overrides,
) -> Dict[str, Any]:
    return _merged(
        {
            "facility_id": facility_id,
            "permit_type": permit_type,
            "issuing_jurisdiction": issuing_jurisdiction,
        },
        overrides,
    )


def permit_decision_payload(
    decision: str = "APPROVE",
    valid_from: Optional[str] = PERMIT_WINDOW_FROM,
    valid_to: Optional[str] = PERMIT_WINDOW_TO,
) -> Dict[str, Any]:
    """`APPROVE` supplies both dates; `DENY` needs none."""
    if decision == "DENY":
        return {"decision": "DENY"}
    payload: Dict[str, Any] = {"decision": decision}
    if valid_from is not None:
        payload["valid_from"] = valid_from
    if valid_to is not None:
        payload["valid_to"] = valid_to
    return payload


# ─── Technicians ──────────────────────────────────────────────────────────────

def technician_payload(
    full_name: str = "Tara Alvarez",
    home_state_code: str = "TX",
    license_state_code: str = "KS",
    license_expires_at: str = "2027-01-31",
    skill_tier: str = "MASTER",
    flat_split_pct: float = 0.45,
    **overrides,
) -> Dict[str, Any]:
    return _merged(
        {
            "full_name": full_name,
            "home_state_code": home_state_code,
            "license_state_code": license_state_code,
            "license_expires_at": license_expires_at,
            "skill_tier": skill_tier,
            "flat_split_pct": flat_split_pct,
        },
        overrides,
    )


# ─── Housing units ────────────────────────────────────────────────────────────

def housing_unit_payload(
    facility_id: str,
    label: str = "Ramada 214",
    bed_count: int = 2,
    nightly_rate_cents: int = 8900,
    **overrides,
) -> Dict[str, Any]:
    return _merged(
        {
            "facility_id": facility_id,
            "label": label,
            "bed_count": bed_count,
            "nightly_rate_cents": nightly_rate_cents,
        },
        overrides,
    )


# ─── Crew deployments ─────────────────────────────────────────────────────────

def crew_deployment_payload(
    technician_id: str,
    facility_id: str,
    start_date: str = DEPLOYMENT_START,
    end_date: str = DEPLOYMENT_END,
    housing_unit_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "technician_id": technician_id,
        "facility_id": facility_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if housing_unit_id is not None:
        payload["housing_unit_id"] = housing_unit_id
    return _merged(payload, overrides)


def crew_deployment_status_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


# ─── Insurers and rate agreements ─────────────────────────────────────────────

def insurer_payload(**overrides) -> Dict[str, Any]:
    return _merged(DEFAULT_INSURER, overrides)


def rate_agreement_payload(insurer_id: str, storm_event_id: str, **overrides) -> Dict[str, Any]:
    return _merged(
        {
            "insurer_id": insurer_id,
            "storm_event_id": storm_event_id,
            **DEFAULT_RATE_AGREEMENT,
        },
        overrides,
    )


def rate_agreement_activate_payload(expected_insurer_version: int) -> Dict[str, Any]:
    return {"expected_insurer_version": expected_insurer_version}


# ─── Vehicles ─────────────────────────────────────────────────────────────────

def vehicle_payload(facility_id: str, insurer_id: str, **overrides) -> Dict[str, Any]:
    return _merged(
        {"facility_id": facility_id, "insurer_id": insurer_id, **DEFAULT_VEHICLE},
        overrides,
    )


def billing_payload(action: str) -> Dict[str, Any]:
    return {"action": action}


# ─── Damage lines ─────────────────────────────────────────────────────────────

def damage_line_payload(
    vehicle_id: str,
    panel_code: str = "HOOD",
    dent_count: int = 42,
    dent_size_class: str = "NICKEL",
    aluminum: bool = False,
    conventional_labor_hours: float = 8.0,
    conventional_paint_materials_cents: int = 25000,
    r_and_i_hours: Optional[float] = 0,
    oversize_dent_count: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "panel_code": panel_code,
        "dent_count": dent_count,
        "dent_size_class": dent_size_class,
        "aluminum": aluminum,
        "conventional_labor_hours": conventional_labor_hours,
        "conventional_paint_materials_cents": conventional_paint_materials_cents,
    }
    if r_and_i_hours is not None:
        payload["r_and_i_hours"] = r_and_i_hours
    if oversize_dent_count is not None:
        payload["oversize_dent_count"] = oversize_dent_count
    return _merged(payload, overrides)


# ─── Work tickets ─────────────────────────────────────────────────────────────

def work_ticket_payload(
    vehicle_id: str,
    technician_id: str,
    labor_units: float = 3.0,
    dents_repaired: int = 42,
    panels_worked: int = 1,
    **overrides,
) -> Dict[str, Any]:
    return _merged(
        {
            "vehicle_id": vehicle_id,
            "technician_id": technician_id,
            "labor_units": labor_units,
            "dents_repaired": dents_repaired,
            "panels_worked": panels_worked,
        },
        overrides,
    )


# ─── Supplements ──────────────────────────────────────────────────────────────

def supplement_payload(
    vehicle_id: str,
    requested_amount_cents: int,
    expected_vehicle_version: int,
    reason_code: str = "HIDDEN_DAMAGE",
    supersedes_supplement_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "reason_code": reason_code,
        "requested_amount_cents": requested_amount_cents,
        "expected_vehicle_version": expected_vehicle_version,
    }
    if supersedes_supplement_id is not None:
        payload["supersedes_supplement_id"] = supersedes_supplement_id
    return _merged(payload, overrides)


def supplement_review_payload(
    decision: str, counter_amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if counter_amount_cents is not None:
        payload["counter_amount_cents"] = counter_amount_cents
    return payload


def supplement_revise_payload(
    action: str = "REVISE", revised_amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if revised_amount_cents is not None:
        payload["revised_amount_cents"] = revised_amount_cents
    return payload


# ─── Quality inspections ──────────────────────────────────────────────────────

def quality_inspection_payload(
    vehicle_id: str,
    inspector_technician_id: str,
    result: str = "PASS",
    defect_panel_codes: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "inspector_technician_id": inspector_technician_id,
        "result": result,
    }
    if defect_panel_codes is not None:
        payload["defect_panel_codes"] = defect_panel_codes
    return _merged(payload, overrides)
