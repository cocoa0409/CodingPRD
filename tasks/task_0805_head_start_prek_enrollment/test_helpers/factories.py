"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PROGRAM_NAME": "Head Start Center",
    "PROGRAM_TYPE": "HEAD_START",
    "FUNDED_ENROLLMENT": 4,
    "AGE_CUTOFF_DATE": "2026-09-01",
    "TOTAL_INSTRUCTIONAL_DAYS": 160,
    "AGE_BAND": "PRESCHOOL_4",
    "FUNDED_SLOTS": 2,
    "MIN_AGE_MONTHS": 48,
    "MAX_AGE_MONTHS": 60,
    "SESSION_START": "09:00",
    "SESSION_END": "12:00",
    "GUARDIAN_NAME": "B Guardian",
    "HOUSEHOLD_SIZE": 3,
    "ANNUAL_INCOME_CENTS": 800_000,
    "CATEGORICAL": "TANF",
    "CHILD_FIRST_NAME": "Bo",
    "CHILD_LAST_NAME": "B",
    "CHILD_DOB": "2022-01-10",
    "TARGET_SCHOOL": "Lincoln Elementary",
    "TRANSITION_DATE": "2026-08-20",
}


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "program_type": DEFAULTS["PROGRAM_TYPE"],
        "funded_enrollment": DEFAULTS["FUNDED_ENROLLMENT"],
        "age_cutoff_date": DEFAULTS["AGE_CUTOFF_DATE"],
        "total_instructional_days": DEFAULTS["TOTAL_INSTRUCTIONAL_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_cohort_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "age_band": DEFAULTS["AGE_BAND"],
        "funded_slots": DEFAULTS["FUNDED_SLOTS"],
        "min_age_months": DEFAULTS["MIN_AGE_MONTHS"],
        "max_age_months": DEFAULTS["MAX_AGE_MONTHS"],
        "session_start": DEFAULTS["SESSION_START"],
        "session_end": DEFAULTS["SESSION_END"],
    }
    payload.update(overrides)
    return payload


def create_family_payload(**overrides) -> dict:
    payload = {
        "guardian_name": DEFAULTS["GUARDIAN_NAME"],
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
        "categorical_eligibility": DEFAULTS["CATEGORICAL"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(program_id, cohort_id, family_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "cohort_id": cohort_id,
        "family_id": family_id,
        "child_first_name": DEFAULTS["CHILD_FIRST_NAME"],
        "child_last_name": DEFAULTS["CHILD_LAST_NAME"],
        "child_dob": DEFAULTS["CHILD_DOB"],
    }
    payload.update(overrides)
    return payload


def create_attendance_payload(enrollment_id, attendance_date, status, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "attendance_date": attendance_date,
        "status": status,
    }
    payload.update(overrides)
    return payload


def create_health_screening_payload(enrollment_id, screening_type="IMMUNIZATION",
                                    due_date="2026-03-15", **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "screening_type": screening_type,
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload


def create_home_visit_payload(enrollment_id, scheduled_date, window_start,
                              window_end, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "scheduled_date": scheduled_date,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_transition_plan_payload(enrollment_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "target_school": DEFAULTS["TARGET_SCHOOL"],
        "transition_date": DEFAULTS["TRANSITION_DATE"],
    }
    payload.update(overrides)
    return payload


def create_pir_report_payload(program_id, reporting_period="2025-2026", **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "reporting_period": reporting_period,
    }
    payload.update(overrides)
    return payload
