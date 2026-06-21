"""Payload factories — one per entity, input fields only."""


def create_therapist_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Clinician"}
    defaults.update(overrides)
    return defaults


def create_state_license_payload(therapist_id, **overrides) -> dict:
    defaults = {
        "therapist_id": therapist_id,
        "state_code": "CA",
        "license_number": "L-TEST",
        "expires_on": "2030-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_supervision_log_payload(therapist_id, supervisor_id, **overrides) -> dict:
    defaults = {
        "therapist_id": therapist_id,
        "supervisor_id": supervisor_id,
        "hours": 1.0,
        "logged_on": "2026-06-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "location_state_code": "CA",
        "annual_household_income": 90000,
        "household_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(patient_id, contract_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "contract_id": contract_id,
        "cost_share_model": "COPAY",
    }
    defaults.update(overrides)
    return defaults


def create_payer_contract_payload(**overrides) -> dict:
    defaults = {
        "payer_name": "Test Payer",
        "in_network": True,
        "contracted_rate_90791_cents": 18000,
        "contracted_rate_90834_cents": 13000,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(therapist_id, patient_id, **overrides) -> dict:
    defaults = {
        "therapist_id": therapist_id,
        "patient_id": patient_id,
        "cpt_code": "90834",
        "modality": "IN_PERSON",
        "start_at": "2026-06-01T08:00:00Z",
        "duration_minutes": 45,
        "payment_path": "SELF_PAY",
    }
    defaults.update(overrides)
    return defaults


def create_clinical_note_payload(appointment_id, **overrides) -> dict:
    defaults = {"appointment_id": appointment_id, "narrative": "Progress note."}
    defaults.update(overrides)
    return defaults


def create_claim_payload(appointment_id, expected_appointment_version, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "expected_appointment_version": expected_appointment_version,
    }
    defaults.update(overrides)
    return defaults


def create_crisis_assessment_payload(patient_id, therapist_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "therapist_id": therapist_id,
        "ideation_score": 0,
        "plan_score": 0,
        "means_access_score": 0,
        "prior_attempts_score": 0,
    }
    defaults.update(overrides)
    return defaults


def create_safety_plan_payload(crisis_assessment_id, **overrides) -> dict:
    defaults = {
        "crisis_assessment_id": crisis_assessment_id,
        "warning_signs": "documented warning signs",
        "coping_strategies": "documented coping strategies",
        "emergency_contacts": ["988"],
    }
    defaults.update(overrides)
    return defaults
