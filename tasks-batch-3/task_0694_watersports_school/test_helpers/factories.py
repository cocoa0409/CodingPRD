"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying only the client-supplied (source: input)
fields for the corresponding create endpoint. Pass **overrides to control any
value a test cares about.
"""

DEFAULTS = {
    "SCHOOL_NAME": "Test School",
    "COURSE_TITLE": "Test Course",
    "LEVEL_NAME": "Level 1",
    "INSTRUCTOR_NAME": "Test Instructor",
    "STUDENT_NAME": "Test Student",
    "ASSET_TAG": "ASSET-1",
    "SIGNER": "Test Signer",
    "BIRTHDATE": "2000-01-01",
    "WAIVER_EXPIRES_AT": "2026-12-31T00:00:00Z",
    "BASE_PRICE_CENTS": 5000,
    "HOURLY_RATE_CENTS": 1000,
    "DEPOSIT_CENTS": 0,
}


def create_school_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["SCHOOL_NAME"]}
    defaults.update(overrides)
    return defaults


def create_course_payload(school_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "discipline": "SURF",
        "title": DEFAULTS["COURSE_TITLE"],
        "kind": "LESSON",
    }
    defaults.update(overrides)
    return defaults


def create_level_payload(course_id, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "rank": 1,
        "name": DEFAULTS["LEVEL_NAME"],
        "max_students_per_instructor": 4,
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "min_age": 0,
        "requires_swim_test": False,
        "required_equipment_type": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(school_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "full_name": DEFAULTS["INSTRUCTOR_NAME"],
        "certified_disciplines": ["SURF"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(school_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "equipment_type": "BOARD",
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(school_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "full_name": DEFAULTS["STUDENT_NAME"],
        "birthdate": DEFAULTS["BIRTHDATE"],
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "signed_by": DEFAULTS["SIGNER"],
        "expires_at": DEFAULTS["WAIVER_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "tier": "BASIC",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(school_id, student_id, course_level_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "student_id": student_id,
        "course_level_id": course_level_id,
        "planned_sessions": 1,
        "party_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(school_id, course_level_id, instructor_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "course_level_id": course_level_id,
        "instructor_id": instructor_id,
        "starts_at": "2026-03-10T09:00:00Z",
        "ends_at": "2026-03-10T10:00:00Z",
        "tide_window_start": "2026-03-10T08:00:00Z",
        "tide_window_end": "2026-03-10T12:00:00Z",
        "capacity": 4,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(session_id, enrollment_id, expected_session_version, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "enrollment_id": enrollment_id,
        "expected_session_version": expected_session_version,
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(school_id, student_id, equipment_item_id,
                          expected_equipment_version, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "student_id": student_id,
        "equipment_item_id": equipment_item_id,
        "expected_equipment_version": expected_equipment_version,
        "starts_at": "2026-03-02T09:00:00Z",
        "ends_at": "2026-03-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults
