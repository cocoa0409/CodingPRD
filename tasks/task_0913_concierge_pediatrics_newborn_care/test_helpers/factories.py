"""Payload factories — one per entity, input fields only."""

from typing import Any, Dict

from .constants import (
    REFERENCE_PLAN_ESSENTIAL,
    REFERENCE_PLAN_PLUS,
    REFERENCE_PLAN_PREMIER,
)

DEFAULTS = {
    "HOUSEHOLD_NAME": "Test Household",
    "FAMILY_MONTHLY_CAP_CENTS": 100_000,
    "PHYSICIAN_NAME": "Dr Ada Reyes",
    "PANEL_SLOT_CAP": 20.0,
    "LICENSED_STATE_CODES": ["CA"],
    "CHILD_FIRST_NAME": "Test Child",
    "DATE_OF_BIRTH": "2026-04-01",
    "CARRIER_NAME": "BlueRidge",
    "DEDUCTIBLE_CENTS": 50_000,
    "COINSURANCE_RATE": 0.20,
    "PATIENT_STATE_CODE": "CA",
}


def create_membership_plan_payload(**overrides) -> Dict[str, Any]:
    """Defaults to the practice's reference `PLUS` tier."""
    payload = dict(REFERENCE_PLAN_PLUS)
    payload.update(overrides)
    return payload


def essential_plan_payload(**overrides) -> Dict[str, Any]:
    payload = dict(REFERENCE_PLAN_ESSENTIAL)
    payload.update(overrides)
    return payload


def plus_plan_payload(**overrides) -> Dict[str, Any]:
    payload = dict(REFERENCE_PLAN_PLUS)
    payload.update(overrides)
    return payload


def premier_plan_payload(**overrides) -> Dict[str, Any]:
    payload = dict(REFERENCE_PLAN_PREMIER)
    payload.update(overrides)
    return payload


def create_physician_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": DEFAULTS["PHYSICIAN_NAME"],
        "panel_slot_cap": DEFAULTS["PANEL_SLOT_CAP"],
        "licensed_state_codes": list(DEFAULTS["LICENSED_STATE_CODES"]),
    }
    payload.update(overrides)
    return payload


def create_family_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "household_name": DEFAULTS["HOUSEHOLD_NAME"],
        "family_monthly_cap_cents": DEFAULTS["FAMILY_MONTHLY_CAP_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_child_payload(family_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "family_id": family_id,
        "first_name": DEFAULTS["CHILD_FIRST_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
    }
    payload.update(overrides)
    return payload


def create_insurance_policy_payload(family_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "family_id": family_id,
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "deductible_cents": DEFAULTS["DEDUCTIBLE_CENTS"],
        "coinsurance_rate": DEFAULTS["COINSURANCE_RATE"],
    }
    payload.update(overrides)
    return payload


def create_membership_payload(
    child_id: str,
    plan_id: str,
    physician_id: str,
    start_date: str,
    expected_family_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "child_id": child_id,
        "plan_id": plan_id,
        "physician_id": physician_id,
        "start_date": start_date,
        "expected_family_version": expected_family_version,
    }
    payload.update(overrides)
    return payload


def cancel_membership_payload(effective_date: str, expected_family_version: int, **overrides):
    payload = {
        "effective_date": effective_date,
        "expected_family_version": expected_family_version,
    }
    payload.update(overrides)
    return payload


def create_waitlist_entry_payload(
    physician_id: str, child_id: str, requested_plan_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "physician_id": physician_id,
        "child_id": child_id,
        "requested_plan_id": requested_plan_id,
    }
    payload.update(overrides)
    return payload


def create_consult_booking_payload(
    membership_id: str,
    consultant_physician_id: str,
    scheduled_start: str,
    scheduled_end: str,
    consult_type: str = "LACTATION_CONSULT",
    modality: str = "IN_PERSON",
    patient_state_code: str = "CA",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "membership_id": membership_id,
        "consult_type": consult_type,
        "consultant_physician_id": consultant_physician_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "modality": modality,
        "patient_state_code": patient_state_code,
    }
    payload.update(overrides)
    return payload


def create_immunization_dose_payload(
    child_id: str, vaccine_code: str, administered_date: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "child_id": child_id,
        "vaccine_code": vaccine_code,
        "administered_date": administered_date,
    }
    payload.update(overrides)
    return payload


def create_encounter_payload(
    membership_id: str,
    started_at: str,
    encounter_type: str = "SICK_VISIT",
    modality: str = "IN_PERSON",
    patient_state_code: str = "CA",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "membership_id": membership_id,
        "encounter_type": encounter_type,
        "modality": modality,
        "patient_state_code": patient_state_code,
        "started_at": started_at,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(
    allowed_amount_cents: int, expected_policy_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "allowed_amount_cents": allowed_amount_cents,
        "expected_policy_version": expected_policy_version,
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(family_id: str, cycle_start_date: str, **overrides):
    payload = {"family_id": family_id, "cycle_start_date": cycle_start_date}
    payload.update(overrides)
    return payload


def create_form_request_payload(
    membership_id: str,
    form_type: str = "SCHOOL",
    needed_by_date: str = "2026-08-01",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "membership_id": membership_id,
        "form_type": form_type,
        "needed_by_date": needed_by_date,
    }
    payload.update(overrides)
    return payload
