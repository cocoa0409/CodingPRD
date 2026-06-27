"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only source: input fields appear here; computed and
system fields (capacity, age_months, status, version, ...) are never sent.
"""

DEFAULTS = {
    "LOCATION_NAME": "Main Pool",
    "LEVEL_NAME": "Level 1",
    "PARENT_NAME": "Pat Parent",
    "PARENT_EMAIL": "pat@x.com",
    "STUDENT_NAME": "Kid One",
    "INSTRUCTOR_NAME": "Coach A",
    "MONTHLY_TUITION_CENTS": 12000,
    "RATIO": 4,
    "MIN_AGE_MONTHS": 36,
    "MAX_AGE_MONTHS": 72,
}


def create_location_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["LOCATION_NAME"]}
    defaults.update(overrides)
    return defaults


def create_level_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LEVEL_NAME"],
        "sequence_order": 1,
        "min_age_months": DEFAULTS["MIN_AGE_MONTHS"],
        "max_age_months": DEFAULTS["MAX_AGE_MONTHS"],
        "max_students_per_instructor": DEFAULTS["RATIO"],
        "monthly_tuition_cents": DEFAULTS["MONTHLY_TUITION_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_skill_payload(**overrides) -> dict:
    defaults = {"name": "Back Float 10s"}
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    defaults = {"full_name": DEFAULTS["INSTRUCTOR_NAME"]}
    defaults.update(overrides)
    return defaults


def create_parent_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PARENT_NAME"],
        "email": DEFAULTS["PARENT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(current_level_id, **overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STUDENT_NAME"],
        "birthdate": "2021-01-01T00:00:00Z",
        "current_level_id": current_level_id,
    }
    defaults.update(overrides)
    return defaults


def create_class_session_payload(location_id, level_id, instructor_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "level_id": level_id,
        "instructor_id": instructor_id,
        "lane_number": 1,
        "day_of_week": 1,
        "start_minute": 600,
        "end_minute": 645,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, class_session_id, expected_class_session_version, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "class_session_id": class_session_id,
        "expected_class_session_version": expected_class_session_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(parent_id, cycle_start, cycle_end, due_at, **overrides) -> dict:
    defaults = {
        "parent_id": parent_id,
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "due_at": due_at,
        "variant": "FORWARD_LOOKING",
    }
    defaults.update(overrides)
    return defaults


def create_makeup_booking_payload(makeup_credit_id, target_class_session_id, occurrence_date, **overrides) -> dict:
    defaults = {
        "makeup_credit_id": makeup_credit_id,
        "target_class_session_id": target_class_session_id,
        "occurrence_date": occurrence_date,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(enrollment_id, skill_scores, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "skill_scores": skill_scores,
    }
    defaults.update(overrides)
    return defaults
