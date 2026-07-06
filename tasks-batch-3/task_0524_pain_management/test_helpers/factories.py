"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CLINIC_NAME": "Test Pain Clinic",
    "STATE_CODE": "CA",
    "PROVIDER_NAME": "Dr Test",
    "DEA_NUMBER": "BX1234567",
    "PATIENT_NAME": "Test Patient",
    "REFERRAL_SOURCE": "Dr Referrer",
    "SUITE_NAME": "Suite-A",
    "PAYER": "Aetna",
    "DRUG_NAME": "oxycodone",
}


def create_clinic_payload(**overrides) -> dict:
    """Clinic: name + state_code required; med_review_threshold_mg + pill_count_tolerance optional."""
    defaults = {
        "name": DEFAULTS["CLINIC_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    """Provider: full_name, dea_number, role_kind."""
    defaults = {
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "dea_number": DEFAULTS["DEA_NUMBER"],
        "role_kind": "PRESCRIBER",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    """Patient: full_name + referral_source."""
    defaults = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "referral_source": DEFAULTS["REFERRAL_SOURCE"],
    }
    defaults.update(overrides)
    return defaults


def create_opioid_agreement_payload(patient_id, prescriber_id, **overrides) -> dict:
    defaults = {"patient_id": patient_id, "prescriber_id": prescriber_id}
    defaults.update(overrides)
    return defaults


def create_pdmp_check_payload(patient_id, queried_by_provider_id, **overrides) -> dict:
    """PdmpCheck: patient_id, queried_by_provider_id, outcome required; outside_med_mg optional."""
    defaults = {
        "patient_id": patient_id,
        "queried_by_provider_id": queried_by_provider_id,
        "outcome": "CLEAR",
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(**overrides) -> dict:
    defaults = {"modality": "MEDICATION"}
    defaults.update(overrides)
    return defaults


def create_fluoroscopy_suite_payload(**overrides) -> dict:
    """Suite: name required; cleanup_buffer_minutes optional."""
    defaults = {"name": DEFAULTS["SUITE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_prior_authorization_payload(**overrides) -> dict:
    defaults = {
        "target_kind": "PRESCRIPTION",
        "payer": DEFAULTS["PAYER"],
        "authorized_units": 30,
    }
    defaults.update(overrides)
    return defaults


def create_procedure_payload(treatment_plan_id, suite_id, prior_auth_id, **overrides) -> dict:
    defaults = {
        "treatment_plan_id": treatment_plan_id,
        "suite_id": suite_id,
        "prior_auth_id": prior_auth_id,
        "start_utc": "2026-06-10T10:00:00Z",
        "duration_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(prescriber_id, **overrides) -> dict:
    """Prescription: prescriber_id, drug_name, dose_mg, units_per_day, conversion_factor,
    day_supply, pills_dispensed required; prior_auth_id + taper_step_pct optional."""
    defaults = {
        "prescriber_id": prescriber_id,
        "drug_name": DEFAULTS["DRUG_NAME"],
        "dose_mg": 15,
        "units_per_day": 6,
        "conversion_factor": 1.5,
        "day_supply": 30,
        "pills_dispensed": 180,
    }
    defaults.update(overrides)
    return defaults


def create_urine_drug_screen_payload(**overrides) -> dict:
    defaults = {
        "due_utc": "2026-06-01T00:00:00Z",
        "expected_substances": ["oxycodone"],
    }
    defaults.update(overrides)
    return defaults


def create_pill_count_audit_payload(prescription_id, **overrides) -> dict:
    defaults = {
        "prescription_id": prescription_id,
        "audit_utc": "2026-06-21T00:00:00Z",
        "counted_pills": 22,
    }
    defaults.update(overrides)
    return defaults
