"""Request-payload factories.

Every factory returns only client-supplied input fields; derived figures, ids,
timestamps and version counters are minted by the server.
"""
from typing import Any, Dict, List, Optional

from .constants import CLOCK_DEFAULT_UTC


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


def build_engineer_payload(
    full_name: str = "Dana Ruiz",
    license_state: str = "TX",
    license_number: str = "PE-77120",
    license_status: Optional[str] = None,
    discipline: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "full_name": full_name,
            "license_state": license_state,
            "license_number": license_number,
            "license_status": license_status,
            "discipline": discipline,
        }
    )
    payload.update(overrides)
    return payload


def build_ahj_reviewer_payload(
    full_name: str = "Marisol Vega",
    jurisdiction_code: str = "TX-AUS",
    discipline: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "full_name": full_name,
            "jurisdiction_code": jurisdiction_code,
            "discipline": discipline,
        }
    )
    payload.update(overrides)
    return payload


def build_clock_payload(current_utc: str = CLOCK_DEFAULT_UTC) -> Dict[str, Any]:
    return {"current_utc": current_utc}


def build_project_payload(
    lead_engineer_id: str,
    ahj_reviewer_id: str,
    project_number: str = "FP-2601",
    building_name: str = "Rio Grande Distribution Center",
    jurisdiction_code: str = "TX-AUS",
    jurisdiction_state: str = "TX",
    occupancy_type: str = "STORAGE",
    building_height_ft: float = 42.0,
    underground_lead_in_loss_psi: Optional[float] = 5.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "project_number": project_number,
            "building_name": building_name,
            "jurisdiction_code": jurisdiction_code,
            "jurisdiction_state": jurisdiction_state,
            "occupancy_type": occupancy_type,
            "building_height_ft": building_height_ft,
            "underground_lead_in_loss_psi": underground_lead_in_loss_psi,
            "lead_engineer_id": lead_engineer_id,
            "ahj_reviewer_id": ahj_reviewer_id,
        }
    )
    payload.update(overrides)
    return payload


def build_fee_payment_payload(amount_usd: float) -> Dict[str, Any]:
    return {"amount_usd": amount_usd}


def build_hazard_area_payload(
    project_id: str,
    label: str = "Rack Storage Bay A",
    hazard_class: str = "ORDINARY_2",
    commodity_class: str = "CLASS_IV",
    storage_height_ft: float = 18.0,
    ceiling_height_ft: float = 36.0,
    area_sqft: float = 24000.0,
    sprinkler_system_type: str = "WET",
    ceiling_slope_pct: Optional[float] = 4.0,
    room_area_sqft: Optional[float] = 3000.0,
    enclosure_rating_hours: Optional[float] = 2.0,
    room_has_unprotected_opening: Optional[bool] = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "project_id": project_id,
            "label": label,
            "hazard_class": hazard_class,
            "commodity_class": commodity_class,
            "storage_height_ft": storage_height_ft,
            "ceiling_height_ft": ceiling_height_ft,
            "area_sqft": area_sqft,
            "sprinkler_system_type": sprinkler_system_type,
            "ceiling_slope_pct": ceiling_slope_pct,
            "room_area_sqft": room_area_sqft,
            "enclosure_rating_hours": enclosure_rating_hours,
            "room_has_unprotected_opening": room_has_unprotected_opening,
        }
    )
    payload.update(overrides)
    return payload


def build_reclassify_payload(
    hazard_class: str = "EXTRA_1",
    commodity_class: str = "GROUP_A_PLASTIC",
    storage_height_ft: float = 18.0,
    ceiling_height_ft: float = 36.0,
    area_sqft: float = 24000.0,
    ceiling_slope_pct: Optional[float] = 4.0,
    room_area_sqft: Optional[float] = 3000.0,
    enclosure_rating_hours: Optional[float] = 2.0,
    room_has_unprotected_opening: Optional[bool] = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "hazard_class": hazard_class,
            "commodity_class": commodity_class,
            "storage_height_ft": storage_height_ft,
            "ceiling_height_ft": ceiling_height_ft,
            "area_sqft": area_sqft,
            "ceiling_slope_pct": ceiling_slope_pct,
            "room_area_sqft": room_area_sqft,
            "enclosure_rating_hours": enclosure_rating_hours,
            "room_has_unprotected_opening": room_has_unprotected_opening,
        }
    )
    payload.update(overrides)
    return payload


def build_flow_test_payload(
    project_id: str,
    hydrant_tag: str = "H-14",
    static_psi: float = 80.0,
    residual_psi: float = 64.0,
    flow_gpm: float = 2250.0,
    tested_at: str = "2026-06-15T14:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "hydrant_tag": hydrant_tag,
        "static_psi": static_psi,
        "residual_psi": residual_psi,
        "flow_gpm": flow_gpm,
        "tested_at": tested_at,
    }
    payload.update(overrides)
    return payload


def build_water_supply_evaluation_payload(
    project_id: str,
    flow_test_id: str,
    governing_hydraulic_calculation_id: str,
    evaluation_basis: str = "RAW_TEST",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "flow_test_id": flow_test_id,
        "governing_hydraulic_calculation_id": governing_hydraulic_calculation_id,
        "evaluation_basis": evaluation_basis,
    }
    payload.update(overrides)
    return payload


def build_hydraulic_calculation_payload(
    project_id: str,
    hazard_area_id: str,
    method: str = "AREA_DENSITY",
    k_factor: float = 25.2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "hazard_area_id": hazard_area_id,
        "method": method,
        "k_factor": k_factor,
    }
    payload.update(overrides)
    return payload


def build_iteration_payload(
    iteration_index: int,
    pipe_size_in: str,
    length_ft: float,
    fitting_equivalent_ft: float,
    flow_gpm: float,
    elevation_change_ft: float,
    is_supply_connection: Optional[bool] = None,
    restart_chain: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "iteration_index": iteration_index,
            "pipe_size_in": pipe_size_in,
            "length_ft": length_ft,
            "fitting_equivalent_ft": fitting_equivalent_ft,
            "flow_gpm": flow_gpm,
            "elevation_change_ft": elevation_change_ft,
            "is_supply_connection": is_supply_connection,
            "restart_chain": restart_chain,
        }
    )
    payload.update(overrides)
    return payload


def build_qc_review_payload(
    disposition: str = "PASS", review_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = _prune({"disposition": disposition, "review_note": review_note})
    payload.update(overrides)
    return payload


def build_fire_pump_payload(
    project_id: str,
    water_supply_evaluation_id: str,
    expected_water_supply_evaluation_version: int,
    model_tag: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "project_id": project_id,
            "water_supply_evaluation_id": water_supply_evaluation_id,
            "model_tag": model_tag,
            "expected_water_supply_evaluation_version": expected_water_supply_evaluation_version,
        }
    )
    payload.update(overrides)
    return payload


def build_auxiliary_system_payload(
    project_id: str,
    system_type: str,
    label: str = "Auxiliary System",
    agent_type: Optional[str] = None,
    riser_count: Optional[int] = None,
    appliance_count: Optional[int] = None,
    water_wash_enabled: Optional[bool] = None,
    in_rack_head_count: Optional[int] = None,
    hazard_area_id: Optional[str] = None,
    protected_area_sqft: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "project_id": project_id,
            "label": label,
            "system_type": system_type,
            "agent_type": agent_type,
            "riser_count": riser_count,
            "appliance_count": appliance_count,
            "water_wash_enabled": water_wash_enabled,
            "in_rack_head_count": in_rack_head_count,
            "hazard_area_id": hazard_area_id,
            "protected_area_sqft": protected_area_sqft,
        }
    )
    payload.update(overrides)
    return payload


def build_commission_payload(
    outage_start_at: str,
    outage_end_at: str,
    interlock_verified: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "outage_start_at": outage_start_at,
            "outage_end_at": outage_end_at,
            "interlock_verified": interlock_verified,
        }
    )
    payload.update(overrides)
    return payload


def build_withdraw_payload(withdraw_note: Optional[str] = None) -> Dict[str, Any]:
    return _prune({"withdraw_note": withdraw_note})


def build_shop_drawing_payload(
    project_id: str,
    hydraulic_calculation_id: str,
    sheet_number: str = "FP-101",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "hydraulic_calculation_id": hydraulic_calculation_id,
        "sheet_number": sheet_number,
    }
    payload.update(overrides)
    return payload


def build_trade_clearance_payload(
    trade: str,
    elevation_low_in: float,
    elevation_high_in: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "trade": trade,
        "elevation_low_in": elevation_low_in,
        "elevation_high_in": elevation_high_in,
    }
    payload.update(overrides)
    return payload


def build_record_clearance_payload(
    outcome: str = "CLEARED",
    conflict_severity: Optional[str] = None,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {"outcome": outcome, "conflict_severity": conflict_severity, "note": note}
    )
    payload.update(overrides)
    return payload


def build_submittal_payload(
    project_id: str,
    included_calculation_ids: List[str],
    expected_project_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "included_calculation_ids": list(included_calculation_ids),
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def build_resubmit_payload(
    included_calculation_ids: List[str],
    expected_project_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "included_calculation_ids": list(included_calculation_ids),
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def build_review_comment_payload(
    code_section: str = "NFPA 13 23.4.4.7",
    severity: str = "MAJOR",
    description: str = "Remote area demand is not demonstrated at the base of riser.",
    assigned_engineer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "code_section": code_section,
            "severity": severity,
            "description": description,
            "assigned_engineer_id": assigned_engineer_id,
        }
    )
    payload.update(overrides)
    return payload


def build_comment_response_payload(
    response_note: str = "Chain re-run and remote area corrected.",
) -> Dict[str, Any]:
    return {"response_note": response_note}


def build_comment_close_payload(
    disposition: str = "RESOLVED",
    close_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune({"disposition": disposition, "close_note": close_note})
    payload.update(overrides)
    return payload


def build_acceptance_test_payload(
    project_id: str, test_type: str = "SYSTEM_FLOW_TEST", **overrides: Any
) -> Dict[str, Any]:
    payload = {"project_id": project_id, "test_type": test_type}
    payload.update(overrides)
    return payload


def build_schedule_witness_payload(
    witness_window_start: str,
    witness_window_end: str,
    witness_reviewer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "witness_window_start": witness_window_start,
            "witness_window_end": witness_window_end,
            "witness_reviewer_id": witness_reviewer_id,
        }
    )
    payload.update(overrides)
    return payload


def build_record_witness_payload(
    measured_flow_gpm: float, measured_residual_psi: float, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "measured_flow_gpm": measured_flow_gpm,
        "measured_residual_psi": measured_residual_psi,
    }
    payload.update(overrides)
    return payload


def build_as_built_payload(
    as_built_document_ref: str = "AB-FP-2601-R1",
) -> Dict[str, Any]:
    return {"as_built_document_ref": as_built_document_ref}


def build_as_built_disposition_payload(
    disposition: str = "ACCEPTED", **overrides: Any
) -> Dict[str, Any]:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload
