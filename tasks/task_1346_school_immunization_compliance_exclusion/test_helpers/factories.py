"""Payload factories — one per creatable resource, input fields only (PRD section 4)."""
from .constants import SCHOOL_YEAR_DEFAULT, TEST_DEFAULTS


def create_student_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Student",
        "date_of_birth": TEST_DEFAULTS["DATE_OF_BIRTH"],
        "grade": TEST_DEFAULTS["GRADE"],
        "school_code": "SCH-1",
        "enrollment_date": TEST_DEFAULTS["ENROLLMENT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_vaccine_requirement_payload(**overrides) -> dict:
    defaults = {
        "vaccine_code": TEST_DEFAULTS["VACCINE_CODE"],
        "applies_to_grades": [TEST_DEFAULTS["GRADE"]],
        "doses_required": TEST_DEFAULTS["DOSES_REQUIRED"],
        "min_interval_days": TEST_DEFAULTS["MIN_INTERVAL_DAYS"],
        "min_age_months": TEST_DEFAULTS["MIN_AGE_MONTHS"],
        "school_year": SCHOOL_YEAR_DEFAULT,
    }
    defaults.update(overrides)
    return defaults


def create_immunization_record_payload(student_version, **overrides) -> dict:
    defaults = {
        "vaccine_code": TEST_DEFAULTS["VACCINE_CODE"],
        "dose_number": 1,
        "administered_date": "2026-08-05T00:00:00Z",
        "expected_student_version": student_version,
    }
    defaults.update(overrides)
    return defaults


def create_exemption_request_payload(**overrides) -> dict:
    defaults = {
        "vaccine_code": TEST_DEFAULTS["VACCINE_CODE"],
        "exemption_type": "MEDICAL",
        "document_ref": "doc://exemption-1",
    }
    defaults.update(overrides)
    return defaults


def deny_exemption_payload(**overrides) -> dict:
    defaults = {"denial_reason": "missing physician signature"}
    defaults.update(overrides)
    return defaults


def resubmit_exemption_payload(**overrides) -> dict:
    defaults = {"document_ref": "doc://exemption-2"}
    defaults.update(overrides)
    return defaults


def create_compliance_notice_payload(**overrides) -> dict:
    defaults = {"notice_type": "INITIAL_NONCOMPLIANCE"}
    defaults.update(overrides)
    return defaults


def rescind_notice_payload(**overrides) -> dict:
    defaults = {"reason": "clerical error"}
    defaults.update(overrides)
    return defaults


def void_record_payload(**overrides) -> dict:
    defaults = {"reason": "recorded under wrong student"}
    defaults.update(overrides)
    return defaults


def create_outbreak_event_payload(**overrides) -> dict:
    defaults = {
        "school_code": "SCH-1",
        "vaccine_code": TEST_DEFAULTS["VACCINE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_clinic_session_payload(**overrides) -> dict:
    defaults = {
        "school_code": "SCH-C1",
        "session_date": TEST_DEFAULTS["SESSION_DATE"],
        "duration_minutes": 120,
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(student_id, session_version, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "vaccine_code": TEST_DEFAULTS["VACCINE_CODE"],
        "start_time": "2026-09-01T10:00:00Z",
        "end_time": "2026-09-01T10:30:00Z",
        "expected_clinic_session_version": session_version,
    }
    defaults.update(overrides)
    return defaults


def create_registry_sync_run_payload(**overrides) -> dict:
    defaults = {"school_code": "SCH-1"}
    defaults.update(overrides)
    return defaults


def seed_registry_dose_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "vaccine_code": TEST_DEFAULTS["VACCINE_CODE"],
        "dose_number": 2,
        "administered_date": "2026-08-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def generate_snapshot_payload(**overrides) -> dict:
    defaults = {
        "school_year": SCHOOL_YEAR_DEFAULT,
        "school_code": "SCH-1",
        "grade": TEST_DEFAULTS["GRADE"],
        "census_date": TEST_DEFAULTS["CENSUS_DATE"],
        "rate_variant": "CENSUS_DATE",
    }
    defaults.update(overrides)
    return defaults


def district_rollup_payload(**overrides) -> dict:
    defaults = {
        "school_year": SCHOOL_YEAR_DEFAULT,
        "grade": TEST_DEFAULTS["GRADE"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
