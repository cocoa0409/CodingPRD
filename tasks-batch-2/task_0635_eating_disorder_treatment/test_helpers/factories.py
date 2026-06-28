"""Payload factories — one per entity, input fields only."""


def create_facility_payload(**overrides) -> dict:
    defaults = {"name": "Test Facility"}
    defaults.update(overrides)
    return defaults


def create_program_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "level_of_care": "RESIDENTIAL",
        "bed_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(program_id, facility_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "facility_id": facility_id,
        "name": "Adult AM",
        "age_band": "ADULT",
        "slot_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "full_name": "Test Patient",
        "age_band": "ADULT",
        "bmi": 17.0,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(patient_id, facility_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "facility_id": facility_id,
        "medical_severity": 5,
        "behavioral_severity": 5,
        "psychiatric_severity": 4,
        "motivation_level": 6,
    }
    defaults.update(overrides)
    return defaults


def create_admission_payload(
    patient_id, facility_id, program_id, cohort_id, **overrides
) -> dict:
    defaults = {
        "patient_id": patient_id,
        "facility_id": facility_id,
        "program_id": program_id,
        "cohort_id": cohort_id,
        "requested_length_of_stay_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(admission_id, facility_id, **overrides) -> dict:
    defaults = {
        "admission_id": admission_id,
        "facility_id": facility_id,
        "payer_name": "BlueCo",
        "daily_rate_cents": 100000,
        "coinsurance_pct": 0.20,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(authorization_id, facility_id, decision, **overrides) -> dict:
    defaults = {
        "authorization_id": authorization_id,
        "facility_id": facility_id,
        "decision": decision,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(admission_id, facility_id, **overrides) -> dict:
    defaults = {
        "admission_id": admission_id,
        "facility_id": facility_id,
        "goals_total": 5,
    }
    defaults.update(overrides)
    return defaults


def create_meal_plan_payload(admission_id, facility_id, **overrides) -> dict:
    defaults = {
        "admission_id": admission_id,
        "facility_id": facility_id,
        "required_meals_per_day": 4,
        "supervision_level": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_meal_event_payload(meal_plan_id, admission_id, **overrides) -> dict:
    defaults = {
        "meal_plan_id": meal_plan_id,
        "admission_id": admission_id,
        "meal_type": "BREAKFAST",
        "completion_fraction": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_family_program_payload(admission_id, facility_id, **overrides) -> dict:
    defaults = {
        "admission_id": admission_id,
        "facility_id": facility_id,
        "family_contact_name": "Kin",
        "sessions_required": 2,
    }
    defaults.update(overrides)
    return defaults


def create_discharge_plan_payload(admission_id, facility_id, **overrides) -> dict:
    defaults = {
        "admission_id": admission_id,
        "facility_id": facility_id,
        "aftercare_level_of_care": "IOP",
        "relapse_warning_signs": "skipping meals",
        "relapse_plan_complete": True,
    }
    defaults.update(overrides)
    return defaults
