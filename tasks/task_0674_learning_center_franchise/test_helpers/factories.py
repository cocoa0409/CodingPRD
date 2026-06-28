"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CENTER_NAME": "Test Center",
    "CONTACT_EMAIL": "parent@example.com",
    "CONTACT_NAME": "Test Parent",
    "STUDENT_NAME": "Test Student",
    "BIRTHDATE": "2016-01-01T00:00:00Z",
    "SUBJECT_NAME": "MATH",
    "SUBJECT_CODE": "MATH",
    "LEVEL_LABEL": "L1",
    "INSTRUCTOR_USER_ID": "instr-1",
}

_TERRITORY_SEQ = [0]


def unique_territory_code() -> str:
    """Generate a fresh uppercase territory code (unique within a test run)."""
    _TERRITORY_SEQ[0] += 1
    return f"TER-{_TERRITORY_SEQ[0]:05d}"


def create_center_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CENTER_NAME"],
        "territory_code": overrides.pop("territory_code", unique_territory_code()),
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(center_id, **overrides) -> dict:
    defaults = {"center_id": center_id, "royalty_basis": "ROYALTY_FLOOR"}
    defaults.update(overrides)
    return defaults


def create_subject_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "name": DEFAULTS["SUBJECT_NAME"],
        "code": DEFAULTS["SUBJECT_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_curriculum_level_payload(subject_id, rank, **overrides) -> dict:
    defaults = {
        "subject_id": subject_id,
        "rank": rank,
        "label": DEFAULTS["LEVEL_LABEL"],
        "worksheets_to_master": 2,
        "mastery_score_threshold": 80,
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "contact_name": DEFAULTS["CONTACT_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(family_id, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "full_name": DEFAULTS["STUDENT_NAME"],
        "birthdate": DEFAULTS["BIRTHDATE"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(center_id, student_id, subject_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "student_id": student_id,
        "subject_id": subject_id,
    }
    defaults.update(overrides)
    return defaults


def create_worksheet_payload(enrollment_id, level_id, set_number, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "level_id": level_id,
        "set_number": set_number,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(center_id, start_at, end_at, seat_cap, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "instructor_user_id": DEFAULTS["INSTRUCTOR_USER_ID"],
        "start_at": start_at,
        "end_at": end_at,
        "seat_cap": seat_cap,
    }
    defaults.update(overrides)
    return defaults


def create_attendance_payload(session_id, enrollment_id, expected_session_version, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "enrollment_id": enrollment_id,
        "expected_session_version": expected_session_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(family_id, center_id, period_month, expected_family_version, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "center_id": center_id,
        "period_month": period_month,
        "expected_family_version": expected_family_version,
    }
    defaults.update(overrides)
    return defaults
