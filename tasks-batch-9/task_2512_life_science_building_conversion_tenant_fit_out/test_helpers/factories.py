"""Payload factories: one per creatable resource, plus the action payloads.

Each factory returns only caller-supplied input fields. Defaults are chosen so
that a payload is accepted on its own; every field can be overridden, and a
field explicitly set to ``None`` is removed from the payload so that a test can
exercise a missing required input or an omitted optional flag.
"""

from typing import Any, Dict, Optional

from .constants import CLOCK_START


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides, dropping any key whose override is the sentinel ``_OMIT``."""
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning "leave this key out of the payload entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "_OMIT"


_OMIT = _Omit()
OMIT = _OMIT


def building_payload(**overrides) -> Dict[str, Any]:
    """A registrable base building with generous nameplate figures."""
    payload = {
        "name": "Kendall Square Conversion Block",
        "address_city": "Cambridge",
        "occupancy_status": "PARTIALLY_OCCUPIED",
        "published_floor_to_floor_ft": 15.00,
        "published_live_load_psf": 125.00,
        "published_vibration_class": "VC_C",
        "exhaust_riser_capacity_cfm": 60000,
        "emergency_power_capacity_kw": 800,
        "chilled_water_capacity_tons": 1200,
    }
    return _apply(payload, overrides)


def floor_payload(floor_number: int = 1, **overrides) -> Dict[str, Any]:
    """A floor plate whose as-built figures match a well-performing plate."""
    payload = {
        "floor_number": floor_number,
        "floor_to_floor_ft": 15.00,
        "live_load_psf": 125.00,
        "vibration_class": "VC_C",
        "sprinklered": True,
    }
    return _apply(payload, overrides)


def assessment_payload(**overrides) -> Dict[str, Any]:
    """A screening assessment with no field measurements taken."""
    payload = {
        "assessment_basis": "SCREENING",
        "required_vibration_class": "VC_C",
        "required_exhaust_cfm": 40000,
        "required_power_kw": 500,
    }
    return _apply(payload, overrides)


def scope_item_payload(discipline: str = "LAB_EXHAUST", **overrides) -> Dict[str, Any]:
    """A conversion scope item for one discipline."""
    payload = {
        "discipline": discipline,
        "description": f"{discipline} conversion package",
        "budget_usd": 4200000.00,
        "capacity_delta_cfm": 0,
        "capacity_delta_kw": 0,
    }
    return _apply(payload, overrides)


def amenity_payload(serving_floor_number: int = 1, **overrides) -> Dict[str, Any]:
    """A shared amenity sitting on the named plate."""
    payload = {
        "name": "Central Glasswash",
        "amenity_type": "GLASSWASH",
        "serving_floor_number": serving_floor_number,
        "concurrent_capacity": 2,
    }
    return _apply(payload, overrides)


def tenant_payload(research_type: str = "BSL2_BIOLOGY", **overrides) -> Dict[str, Any]:
    """A prospective tenant with a research programme."""
    payload = {
        "legal_name": f"{research_type.title()} Therapeutics Inc",
        "research_type": research_type,
        "credit_tier": "VENTURE_BACKED",
    }
    return _apply(payload, overrides)


def lease_payload(
    tenant_id: str,
    building_id: str,
    premises_floor_id: str,
    rentable_sf: int = 20000,
    **overrides,
) -> Dict[str, Any]:
    """A lease binding a tenant to a demised plate."""
    payload = {
        "tenant_id": tenant_id,
        "building_id": building_id,
        "premises_floor_id": premises_floor_id,
        "rentable_sf": rentable_sf,
        "term_months": 120,
        "base_rent_psf": 95.00,
        "delivery_deadline": "2027-12-31T00:00:00Z",
    }
    return _apply(payload, overrides)


def proposal_payload(
    expected_lease_version: int, proposed_allowance_psf: float, **overrides
) -> Dict[str, Any]:
    """A negotiation round under its version precondition."""
    payload = {
        "expected_lease_version": expected_lease_version,
        "proposed_allowance_psf": proposed_allowance_psf,
    }
    return _apply(payload, overrides)


def escrow_deposit_payload(amount_usd: float, **overrides) -> Dict[str, Any]:
    payload = {"amount_usd": amount_usd}
    return _apply(payload, overrides)


def disbursement_payload(requested_usd: float, **overrides) -> Dict[str, Any]:
    payload = {"requested_usd": requested_usd}
    return _apply(payload, overrides)


def project_payload(lease_id: str, floor_id: str, **overrides) -> Dict[str, Any]:
    """A fit-out project on the demised plate."""
    payload = {
        "lease_id": lease_id,
        "floor_id": floor_id,
        "design_exhaust_cfm": 12000,
        "design_power_kw": 180,
        "scope_summary": "Full laboratory fit-out of the demised premises",
    }
    return _apply(payload, overrides)


def phase_payload(
    sequence_no: int = 1,
    premium_class: str = "LAB_MEP",
    work_class: str = "QUIET",
    hard_cost_usd: float = 100000.00,
    **overrides,
) -> Dict[str, Any]:
    """A phase package; predecessor and affected amenity are optional."""
    payload = {
        "sequence_no": sequence_no,
        "premium_class": premium_class,
        "work_class": work_class,
        "hard_cost_usd": hard_cost_usd,
        "restoration_cost_usd": 0.00,
    }
    return _apply(payload, overrides)


def schedule_payload(window_start: str, window_end: str, **overrides) -> Dict[str, Any]:
    payload = {"window_start": window_start, "window_end": window_end}
    return _apply(payload, overrides)


def hold_payload(hold_reason: str = "Plate exceeded VC_C during coring", **overrides):
    payload = {"hold_reason": hold_reason}
    return _apply(payload, overrides)


def progress_payload(target_status: str = "IN_PROGRESS", **overrides) -> Dict[str, Any]:
    payload = {"target_status": target_status}
    return _apply(payload, overrides)


def reservation_payload(
    project_id: str,
    expected_building_version: int,
    exhaust_cfm: float = 12000,
    power_kw: float = 180,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "exhaust_cfm": exhaust_cfm,
        "power_kw": power_kw,
        "expected_building_version": expected_building_version,
    }
    return _apply(payload, overrides)


def hazmat_permit_payload(
    project_id: str,
    floor_id: str,
    hazard_class: str = "FLAMMABLE_IB",
    use_condition: str = "CLOSED_SYSTEM_USE",
    quantity_gal: float = 100.00,
    control_area_index: int = 1,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "floor_id": floor_id,
        "hazard_class": hazard_class,
        "use_condition": use_condition,
        "quantity_gal": quantity_gal,
        "control_area_index": control_area_index,
    }
    return _apply(payload, overrides)


def hazmat_decision_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    payload = {"decision": decision}
    return _apply(payload, overrides)


def allocation_payload(
    amenity_id: str,
    project_id: str,
    window_start: str,
    window_end: str,
    headcount: int = 2,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "amenity_id": amenity_id,
        "project_id": project_id,
        "window_start": window_start,
        "window_end": window_end,
        "headcount": headcount,
    }
    return _apply(payload, overrides)


def commissioning_record_payload(
    script_type: str,
    executed_by_user_id: str,
    scheduled_for: str = "2026-11-01T09:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "script_type": script_type,
        "scheduled_for": scheduled_for,
        "executed_by_user_id": executed_by_user_id,
    }
    return _apply(payload, overrides)


def commissioning_result_payload(
    result: str, witnessed_by_user_id: str, **overrides
) -> Dict[str, Any]:
    payload = {"result": result, "witnessed_by_user_id": witnessed_by_user_id}
    return _apply(payload, overrides)


def clock_payload(current_utc: Optional[str] = None, **overrides) -> Dict[str, Any]:
    payload = {"current_utc": current_utc or CLOCK_START}
    return _apply(payload, overrides)


def expiration_notice_payload(expiration_date: str, **overrides) -> Dict[str, Any]:
    payload = {"expiration_date": expiration_date}
    return _apply(payload, overrides)


def assessment_decision_payload(
    decision: str = "ACCEPT", **overrides
) -> Dict[str, Any]:
    payload = {"decision": decision}
    return _apply(payload, overrides)


def permit_decision_payload(decision: str = "ISSUE", **overrides) -> Dict[str, Any]:
    payload = {"decision": decision}
    return _apply(payload, overrides)


def milestone_payload(milestone: str = "SUBSTANTIAL_COMPLETION", **overrides):
    payload = {"milestone": milestone}
    return _apply(payload, overrides)
