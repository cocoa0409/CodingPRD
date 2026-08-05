"""Payload factories — one per create/action endpoint, input fields only."""

from .constants import TEST_DEFAULTS


def school_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SCHOOL_NAME"],
        "site_code": TEST_DEFAULTS["SITE_CODE"],
        "sponsor_hospital_name": TEST_DEFAULTS["SPONSOR_HOSPITAL"],
        "telehealth_concurrent_capacity": 1,
    }
    payload.update(overrides)
    return payload


def clinician_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Reyes NP",
        "discipline": "MEDICAL",
        "license_number": "NP-1001",
    }
    payload.update(overrides)
    return payload


def student_payload(**overrides) -> dict:
    payload = {
        "first_name": "Ava",
        "last_name": "Nguyen",
        "date_of_birth": TEST_DEFAULTS["STUDENT_DOB"],
    }
    payload.update(overrides)
    return payload


def financial_profile_payload(**overrides) -> dict:
    payload = {
        "household_income_annual_cents": TEST_DEFAULTS["TIER_A_INCOME_CENTS"],
        "household_size": TEST_DEFAULTS["TIER_A_HOUSEHOLD_SIZE"],
        "payer_route": "SELF_PAY",
    }
    payload.update(overrides)
    return payload


def guardian_payload(**overrides) -> dict:
    payload = {
        "full_name": "Mai Nguyen",
        "relationship": "MOTHER",
        "contact_email": "mai@example.org",
        "is_primary": True,
    }
    payload.update(overrides)
    return payload


def enrollment_payload(school_id, expected_student_version, school_year="2025-2026", **overrides):
    payload = {
        "school_id": school_id,
        "school_year": school_year,
        "expected_student_version": expected_student_version,
    }
    payload.update(overrides)
    return payload


def consent_payload(
    category,
    granted_by_user_id,
    expected_student_version,
    granted_by="GUARDIAN",
    school_year="2025-2026",
    **overrides,
) -> dict:
    payload = {
        "category": category,
        "school_year": school_year,
        "granted_by": granted_by,
        "granted_by_user_id": granted_by_user_id,
        "expected_student_version": expected_student_version,
    }
    payload.update(overrides)
    return payload


def visit_payload(student_id, school_id, clinician_id, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "school_id": school_id,
        "clinician_id": clinician_id,
        "visit_type": "ACUTE",
        "scheduled_start_at": "2026-05-04T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def dose_payload(series_code, dose_number, administered_date, **overrides) -> dict:
    payload = {
        "series_code": series_code,
        "dose_number": dose_number,
        "administered_date": administered_date,
    }
    payload.update(overrides)
    return payload


def screening_payload(instrument, numeric_result, **overrides) -> dict:
    payload = {"instrument": instrument, "numeric_result": numeric_result}
    payload.update(overrides)
    return payload


def referral_payload(specialty="PRIMARY_CARE", reason="Persistent cough for six weeks", **overrides):
    payload = {"specialty": specialty, "reason": reason}
    payload.update(overrides)
    return payload


def clearance_payload(outcome, expected_student_version, **overrides) -> dict:
    payload = {"outcome": outcome, "expected_student_version": expected_student_version}
    payload.update(overrides)
    return payload


def telehealth_session_payload(visit_id, start_at, end_at, **overrides) -> dict:
    payload = {"visit_id": visit_id, "start_at": start_at, "end_at": end_at}
    payload.update(overrides)
    return payload


def report_payload(period_start_date, period_end_date, **overrides) -> dict:
    payload = {
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
    payload.update(overrides)
    return payload
