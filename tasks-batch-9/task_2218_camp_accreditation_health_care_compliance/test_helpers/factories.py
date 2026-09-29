"""Request payload builders. Each factory emits only client-supplied input fields."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .types import (
    AdministeredByRole,
    CampType,
    HealthStaffingLevel,
    MedicationClass,
    PopulationServed,
    StandardDomain,
)


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


# --------------------------------------------------------------------------
# Camp
# --------------------------------------------------------------------------
def camp_payload(
    name: str = "Pine Day Camp",
    camp_type: str = CampType.DAY,
    state_code: str = "OH",
    population_served: str = PopulationServed.YOUTH_ONLY,
    program_elements: Optional[List[str]] = None,
    resident_census: Optional[int] = 0,
    distance_to_hospital_km: Optional[int] = 0,
    max_daily_census: Optional[int] = 60,
    health_staffing_level: Optional[str] = HealthStaffingLevel.FIRST_AIDER_ONLY,
    prior_accredited_cycle_count: Optional[int] = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "camp_type": camp_type,
        "state_code": state_code,
        "population_served": population_served,
        "program_elements": [] if program_elements is None else program_elements,
        "resident_census": resident_census,
        "distance_to_hospital_km": distance_to_hospital_km,
        "max_daily_census": max_daily_census,
        "health_staffing_level": health_staffing_level,
        "prior_accredited_cycle_count": prior_accredited_cycle_count,
    }
    payload.update(overrides)
    return _drop_none(payload)


def state_license_payload(
    state_license_status: str, state_license_number: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none(
        {
            "state_license_status": state_license_status,
            "state_license_number": state_license_number,
        }
    )


def health_center_payload(
    health_staffing_level: Optional[str] = None,
    resident_census: Optional[int] = None,
    max_daily_census: Optional[int] = None,
    distance_to_hospital_km: Optional[int] = None,
    controlled_intake_units_added: Optional[int] = None,
) -> Dict[str, Any]:
    return _drop_none(
        {
            "health_staffing_level": health_staffing_level,
            "resident_census": resident_census,
            "max_daily_census": max_daily_census,
            "distance_to_hospital_km": distance_to_hospital_km,
            "controlled_intake_units_added": controlled_intake_units_added,
        }
    )


# --------------------------------------------------------------------------
# Standards book
# --------------------------------------------------------------------------
def standards_set_payload(
    edition_code: str = "ACA-2026-A", effective_year: int = 2026, **overrides: Any
) -> Dict[str, Any]:
    payload = {"edition_code": edition_code, "effective_year": effective_year}
    payload.update(overrides)
    return payload


def standard_payload(
    standards_set_id: str,
    code: str = "SU.1",
    title: str = "Staff supervision ratios",
    domain: str = StandardDomain.SUPERVISION,
    mandatory: Optional[bool] = None,
    scoring_weight: Optional[int] = None,
    written_plan_type_required: Optional[str] = None,
    applies_to_camp_types: Optional[List[str]] = None,
    applies_to_populations: Optional[List[str]] = None,
    requires_program_elements_any: Optional[List[str]] = None,
    requires_state_licensed: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "standards_set_id": standards_set_id,
        "code": code,
        "title": title,
        "domain": domain,
        "mandatory": mandatory,
        "scoring_weight": scoring_weight,
        "written_plan_type_required": written_plan_type_required,
        "applies_to_camp_types": applies_to_camp_types,
        "applies_to_populations": applies_to_populations,
        "requires_program_elements_any": requires_program_elements_any,
        "requires_state_licensed": requires_state_licensed,
    }
    payload.update(overrides)
    return _drop_none(payload)


# --------------------------------------------------------------------------
# Cycle, evaluations and plans
# --------------------------------------------------------------------------
def cycle_payload(
    camp_id: str,
    standards_set_id: str,
    expected_camp_version: int,
    cycle_year: int = 2026,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "camp_id": camp_id,
        "standards_set_id": standards_set_id,
        "cycle_year": cycle_year,
        "expected_camp_version": expected_camp_version,
    }
    payload.update(overrides)
    return payload


def self_assessment_payload(
    self_score: str, written_plan_id: Optional[str] = None, note: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none(
        {"self_score": self_score, "written_plan_id": written_plan_id, "note": note}
    )


def visitor_score_payload(
    visitor_score: str, score_source: str, note: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none(
        {"visitor_score": visitor_score, "score_source": score_source, "note": note}
    )


def written_plan_payload(
    camp_id: str,
    plan_type: str,
    expected_camp_version: int,
    body_ref: str = "PLAN-2026-REV1",
    effective_date: str = "2026-05-01",
    expires_at: str = "2027-05-01",
    physician_reviewed: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "camp_id": camp_id,
        "plan_type": plan_type,
        "body_ref": body_ref,
        "effective_date": effective_date,
        "expires_at": expires_at,
        "physician_reviewed": physician_reviewed,
        "expected_camp_version": expected_camp_version,
    }
    payload.update(overrides)
    return _drop_none(payload)


def plan_review_payload(
    decision: str, verification_note: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none({"decision": decision, "verification_note": verification_note})


# --------------------------------------------------------------------------
# Visiting team
# --------------------------------------------------------------------------
def visitor_payload(
    full_name: str = "Lead One",
    home_state_code: str = "PA",
    trained_through_year: int = 2026,
    certifications: Optional[List[str]] = None,
    employer_camp_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "full_name": full_name,
        "home_state_code": home_state_code,
        "trained_through_year": trained_through_year,
        "certifications": [] if certifications is None else certifications,
        "employer_camp_id": employer_camp_id,
    }
    payload.update(overrides)
    return _drop_none(payload)


def visit_payload(
    cycle_id: str,
    expected_cycle_version: int,
    window_start_date: str = "2026-09-01",
    window_end_date: str = "2026-09-05",
    scheduled_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "cycle_id": cycle_id,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "expected_cycle_version": expected_cycle_version,
        "scheduled_note": scheduled_note,
    }
    payload.update(overrides)
    return _drop_none(payload)


def visit_assignment_payload(
    visit_id: str,
    visitor_id: str,
    team_role: str,
    travel_block_start_date: str = "2026-09-01",
    travel_block_end_date: str = "2026-09-03",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "visit_id": visit_id,
        "visitor_id": visitor_id,
        "team_role": team_role,
        "travel_block_start_date": travel_block_start_date,
        "travel_block_end_date": travel_block_end_date,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Deficiency correction
# --------------------------------------------------------------------------
def correction_plan_payload(correction_plan_text: str) -> Dict[str, Any]:
    return {"correction_plan_text": correction_plan_text}


def deficiency_review_payload(
    decision: str, reviewer_note: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none({"decision": decision, "reviewer_note": reviewer_note})


# --------------------------------------------------------------------------
# Health centre records
# --------------------------------------------------------------------------
def medication_record_payload(
    camp_id: str,
    camper_reference: str = "CR-01",
    medication_class: str = MedicationClass.OTC,
    dose_units: int = 1,
    administered_at: str = "2026-08-01T09:00:00.000Z",
    administered_by_role: str = AdministeredByRole.RN,
    second_signature_present: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "camp_id": camp_id,
        "camper_reference": camper_reference,
        "medication_class": medication_class,
        "dose_units": dose_units,
        "administered_at": administered_at,
        "administered_by_role": administered_by_role,
        "second_signature_present": second_signature_present,
    }
    payload.update(overrides)
    return _drop_none(payload)


def void_payload(void_reason: Optional[str] = None) -> Dict[str, Any]:
    return _drop_none({"void_reason": void_reason})


# --------------------------------------------------------------------------
# Annual reporting
# --------------------------------------------------------------------------
def annual_report_payload(camp_id: str, report_year: int = 2026, **overrides: Any) -> Dict[str, Any]:
    payload = {"camp_id": camp_id, "report_year": report_year}
    payload.update(overrides)
    return payload


def annual_report_submit_payload(declared_incident_count: int) -> Dict[str, Any]:
    return {"declared_incident_count": declared_incident_count}


def annual_report_review_payload(
    decision: str, reviewer_note: Optional[str] = None
) -> Dict[str, Any]:
    return _drop_none({"decision": decision, "reviewer_note": reviewer_note})


def incident_disclosure_payload(
    annual_report_id: str,
    incident_type: str,
    occurred_at: str = "2026-07-15T14:30:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "annual_report_id": annual_report_id,
        "incident_type": incident_type,
        "occurred_at": occurred_at,
    }
    payload.update(overrides)
    return payload
