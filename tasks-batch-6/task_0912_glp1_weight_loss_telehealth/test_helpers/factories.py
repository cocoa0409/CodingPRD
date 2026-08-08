"""Payload factories — one per resource, carrying only client-supplied fields."""

import itertools

from .constants import TEST_DEFAULTS

_EMAIL_SEQ = itertools.count(1)
_NPI_SEQ = itertools.count(1710000001)
_LOT_SEQ = itertools.count(1)


def unique_email(prefix: str = "member") -> str:
    return f"{prefix}{next(_EMAIL_SEQ)}@example.com"


def unique_npi() -> str:
    return str(next(_NPI_SEQ))


def unique_lot_code(prefix: str = "L") -> str:
    return f"{prefix}-{next(_LOT_SEQ):04d}"


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Member",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "height_cm": TEST_DEFAULTS["HEIGHT_CM"],
        "weight_kg": TEST_DEFAULTS["WEIGHT_OBESE_KG"],
        "payment_mode": "CASH",
        "comorbidity_codes": [],
    }
    defaults.update(overrides)
    return defaults


def create_clinician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Nia Cole",
        "provider_type": "CLINICIAN",
        "licensed_state_codes": [TEST_DEFAULTS["STATE_CODE"]],
        "npi": unique_npi(),
    }
    defaults.update(overrides)
    return defaults


def create_coach_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Coach Kim",
        "provider_type": "COACH",
        "licensed_state_codes": [TEST_DEFAULTS["STATE_CODE"]],
    }
    defaults.update(overrides)
    return defaults


def create_pharmacy_payload(**overrides) -> dict:
    defaults = {
        "name": "Bay Compounding",
        "dispense_type": "COMPOUNDED",
        "served_state_codes": [TEST_DEFAULTS["STATE_CODE"]],
        "status": "ACTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_supply_lot_payload(pharmacy_id: str, **overrides) -> dict:
    defaults = {
        "pharmacy_id": pharmacy_id,
        "lot_code": unique_lot_code(),
        "strength_mg": 0.25,
        "total_units": 24,
        "window_capacity_units": 6,
        "expires_at": "2026-12-31T00:00:00Z",
        "status": "RELEASED",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "recorded_weight_kg": TEST_DEFAULTS["WEIGHT_OBESE_KG"],
        "egfr": TEST_DEFAULTS["EGFR_NORMAL"],
        "lab_collected_at": TEST_DEFAULTS["FRESH_LAB_COLLECTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_consult_payload(patient_id: str, provider_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "scheduled_start_at": "2026-06-02T15:00:00Z",
        "scheduled_end_at": "2026-06-02T15:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(
    patient_id: str,
    consult_id: str,
    prescriber_provider_id: str,
    screening_id: str,
    expected_patient_version: int,
    **overrides,
) -> dict:
    defaults = {
        "patient_id": patient_id,
        "consult_id": consult_id,
        "prescriber_provider_id": prescriber_provider_id,
        "screening_id": screening_id,
        "drug_family": "SEMAGLUTIDE",
        "units_per_cycle": 2,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_prior_authorization_payload(prescription_id: str, **overrides) -> dict:
    defaults = {"prescription_id": prescription_id, "payer_reference": "PA-70001"}
    defaults.update(overrides)
    return defaults


def create_pharmacy_order_payload(
    prescription_id: str,
    titration_step_id: str,
    expected_prescription_version: int,
    **overrides,
) -> dict:
    defaults = {
        "prescription_id": prescription_id,
        "titration_step_id": titration_step_id,
        "units_requested": 2,
        "window_start_at": "2026-06-02T00:00:00Z",
        "window_end_at": "2026-06-09T00:00:00Z",
        "expected_prescription_version": expected_prescription_version,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(patient_id: str, prescription_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "prescription_id": prescription_id,
        "anchor_at": "2026-06-01T00:00:00Z",
        "coaching_addon_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(patient_id: str, prescription_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "prescription_id": prescription_id,
        "nausea_score": 1,
        "vomiting_score": 1,
        "dehydration_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_coaching_session_payload(
    subscription_id: str, coach_provider_id: str, **overrides
) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "coach_provider_id": coach_provider_id,
        "scheduled_start_at": "2026-06-05T16:00:00Z",
        "scheduled_end_at": "2026-06-05T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults
