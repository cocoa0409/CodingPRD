"""Payload factories — one per entity, carrying only client-supplied inputs.

Money is always a whole number of cents expressed as a Python int, never a
string and never a decimal, exactly as the PRD requires of every field whose
name ends in `_cents`.
"""

from typing import List, Optional

from .constants import TEST_DEFAULTS

_CLIENT_CODE_SEQUENCE = {"next": 1}


def next_client_code(prefix: str = "C") -> str:
    """Allocate a client_code that is unique within one test process."""
    value = _CLIENT_CODE_SEQUENCE["next"]
    _CLIENT_CODE_SEQUENCE["next"] = value + 1
    return f"{prefix}-{9000 + value}"


def create_staff_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Rosa Marin",
        "role_type": "HOTLINE_ADVOCATE",
        "max_caseload": TEST_DEFAULTS["MAX_CASELOAD"],
    }
    payload.update(overrides)
    return payload


def create_wellness_check_payload(**overrides) -> dict:
    payload = {
        "checked_on_utc": "2026-08-01T00:00:00Z",
        "exposure_hours": 4.0,
        "distress_scale": 3,
        "debrief_completed": False,
    }
    payload.update(overrides)
    return payload


def create_client_payload(**overrides) -> dict:
    payload = {
        "client_code": next_client_code(),
        "legal_name": "Ada Vale",
        "household_size": 2,
        "minor_children_count": 0,
        "accessibility_required": False,
        "location_confidential": True,
    }
    payload.update(overrides)
    return payload


def change_consent_payload(hmis_disclosure_consent: str = "GRANTED", **overrides) -> dict:
    payload = {"hmis_disclosure_consent": hmis_disclosure_consent}
    payload.update(overrides)
    return payload


def create_hotline_call_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "caller_type": "SURVIVOR",
        "presenting_concerns": "Needs a safe bed and a plan for the week.",
    }
    payload.update(overrides)
    return payload


def create_risk_assessment_payload(**overrides) -> dict:
    """Defaults are the PRD's worked example: 44 factor points and a 1.10 multiplier."""
    payload = {
        "weapon_access": True,
        "strangulation_history": False,
        "separation_recent": True,
        "threats_to_kill": False,
        "stalking_frequency_per_week": 2,
    }
    payload.update(overrides)
    return payload


def dispose_payload(disposition: str, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def create_safety_plan_payload(
    client_id: str, based_on_risk_assessment_id: str, expected_client_version: int, **overrides
) -> dict:
    payload = {
        "client_id": client_id,
        "based_on_risk_assessment_id": based_on_risk_assessment_id,
        "expected_client_version": expected_client_version,
    }
    payload.update(overrides)
    return payload


def create_plan_component_payload(component_type: str, **overrides) -> dict:
    payload = {
        "component_type": component_type,
        "detail": f"Individualized {component_type.lower().replace('_', ' ')} step.",
        "target_completion_date": "2026-08-20",
    }
    payload.update(overrides)
    return payload


def create_shelter_payload(**overrides) -> dict:
    payload = {
        "name": "Cedar House",
        "confidential_location": True,
        "nightly_rate_cents": TEST_DEFAULTS["NIGHTLY_RATE_CENTS"],
        "weekend_surcharge_cents": TEST_DEFAULTS["WEEKEND_SURCHARGE_CENTS"],
        "child_supplement_cents": TEST_DEFAULTS["CHILD_SUPPLEMENT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_shelter_unit_payload(**overrides) -> dict:
    payload = {
        "unit_label": "A1",
        "unit_type": "STANDARD",
        "bed_capacity": TEST_DEFAULTS["BED_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_screening_request_payload(
    client_id: str, hotline_call_id: str, requested_shelter_id: str, **overrides
) -> dict:
    payload = {
        "client_id": client_id,
        "hotline_call_id": hotline_call_id,
        "requested_shelter_id": requested_shelter_id,
        "requested_entry_date": TEST_DEFAULTS["ENTRY_DATE"],
    }
    payload.update(overrides)
    return payload


def decide_screening_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_shelter_admission_payload(
    screening_request_id: str,
    shelter_unit_id: str,
    expected_shelter_unit_version: int,
    **overrides,
) -> dict:
    payload = {
        "screening_request_id": screening_request_id,
        "shelter_unit_id": shelter_unit_id,
        "entry_date": TEST_DEFAULTS["ENTRY_DATE"],
        "planned_exit_date": TEST_DEFAULTS["PLANNED_EXIT_DATE"],
        "expected_shelter_unit_version": expected_shelter_unit_version,
    }
    payload.update(overrides)
    return payload


def check_in_payload(**overrides) -> dict:
    payload = {"school_enrollment_confirmed": False}
    payload.update(overrides)
    return payload


def exit_payload(actual_exit_date: str, exit_destination: str = "PERMANENT_HOUSING", **overrides) -> dict:
    payload = {"actual_exit_date": actual_exit_date, "exit_destination": exit_destination}
    payload.update(overrides)
    return payload


def cancel_payload(cancel_reason: str = "Household found other refuge.", **overrides) -> dict:
    payload = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


def report_compromise_payload(compromise_source: str = "ABUSER_CONTACT", **overrides) -> dict:
    payload = {"compromise_source": compromise_source}
    payload.update(overrides)
    return payload


def complete_relocation_payload(
    new_shelter_unit_id: str, expected_shelter_unit_version: int, **overrides
) -> dict:
    payload = {
        "new_shelter_unit_id": new_shelter_unit_id,
        "expected_shelter_unit_version": expected_shelter_unit_version,
    }
    payload.update(overrides)
    return payload


def create_protective_order_case_payload(client_id: str, **overrides) -> dict:
    payload = {"client_id": client_id, "order_type": "EMERGENCY_EX_PARTE"}
    payload.update(overrides)
    return payload


def file_protective_order_payload(
    accompanying_advocate_id: str,
    hearing_start_utc: str = "2026-08-05T09:00:00Z",
    hearing_end_utc: str = "2026-08-05T10:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "filed_court": "County Family Court",
        "hearing_start_utc": hearing_start_utc,
        "hearing_end_utc": hearing_end_utc,
        "accompanying_advocate_id": accompanying_advocate_id,
    }
    payload.update(overrides)
    return payload


def record_outcome_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_landlord_partner_payload(**overrides) -> dict:
    payload = {
        "name": "Vista Rentals",
        "units_pledged": TEST_DEFAULTS["UNITS_PLEDGED"],
        "accepts_subsidy_type": "RAPID_REHOUSING_SUBSIDY",
        "base_incentive_cents": TEST_DEFAULTS["BASE_INCENTIVE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_housing_referral_payload(
    client_id: str,
    landlord_partner_id: str,
    program_type: str = "TRANSITIONAL_HOUSING",
    subsidy_type: str = "RAPID_REHOUSING_SUBSIDY",
    **overrides,
) -> dict:
    payload = {
        "client_id": client_id,
        "landlord_partner_id": landlord_partner_id,
        "program_type": program_type,
        "subsidy_type": subsidy_type,
    }
    payload.update(overrides)
    return payload


def match_referral_payload(
    expected_landlord_partner_version: int, monthly_rent_cents: int = 140000, **overrides
) -> dict:
    payload = {
        "monthly_rent_cents": monthly_rent_cents,
        "expected_landlord_partner_version": expected_landlord_partner_version,
    }
    payload.update(overrides)
    return payload


def withdraw_match_payload(withdraw_reason: str = "Landlord relet the flat.", **overrides) -> dict:
    payload = {"withdraw_reason": withdraw_reason}
    payload.update(overrides)
    return payload


def lease_payload(lease_start_date: str, **overrides) -> dict:
    payload = {"lease_start_date": lease_start_date}
    payload.update(overrides)
    return payload


def create_disclosure_event_payload(
    client_id: str,
    requested_by_staff_id: str,
    kind: str,
    requested_field_keys: List[str],
    requester_org: str = "Regional Continuum of Care",
    roi_signed_on: Optional[str] = None,
    roi_expires_on: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "client_id": client_id,
        "requested_by_staff_id": requested_by_staff_id,
        "kind": kind,
        "requester_org": requester_org,
        "requested_field_keys": list(requested_field_keys),
    }
    if roi_signed_on is not None:
        payload["roi_signed_on"] = roi_signed_on
    if roi_expires_on is not None:
        payload["roi_expires_on"] = roi_expires_on
    payload.update(overrides)
    return payload


def decide_disclosure_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
