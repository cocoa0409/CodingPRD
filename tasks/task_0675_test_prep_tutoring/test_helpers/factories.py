"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "EXAM_TYPE": "SAT",
    "FORMAT": "LIVE",
    "TITLE": "SAT Prep",
    "LIST_PRICE_CENTS": 100000,
    "BASELINE_SCALE_MAX": 1600,
    "GUARANTEE_MIN_DELTA": 200,
    "REQUIRED_PRACTICE_TESTS": 1,
    "REQUIRED_ATTENDANCE_PCT": 0.5,
    "MATERIALS_ACCESS_DAYS": 30,
    "SEAT_CAPACITY": 5,
    "STARTS_AT": "2026-06-01T00:00:00Z",
    "ENDS_AT": "2026-06-30T00:00:00Z",
    "TOTAL_SESSIONS": 4,
    "MAX_CONCURRENT_COHORTS": 3,
}


def create_course_payload(**overrides) -> dict:
    """POST /courses — all input fields are required (no defaults declared)."""
    defaults = {
        "exam_type": DEFAULTS["EXAM_TYPE"],
        "format": DEFAULTS["FORMAT"],
        "title": DEFAULTS["TITLE"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
        "baseline_scale_max": DEFAULTS["BASELINE_SCALE_MAX"],
        "guarantee_min_delta": DEFAULTS["GUARANTEE_MIN_DELTA"],
        "required_practice_tests": DEFAULTS["REQUIRED_PRACTICE_TESTS"],
        "required_attendance_pct": DEFAULTS["REQUIRED_ATTENDANCE_PCT"],
        "materials_access_days": DEFAULTS["MATERIALS_ACCESS_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    """POST /instructors — full_name, certified_exam_types, max_concurrent_cohorts."""
    defaults = {
        "full_name": "Iris Instructor",
        "certified_exam_types": ["SAT"],
        "max_concurrent_cohorts": DEFAULTS["MAX_CONCURRENT_COHORTS"],
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(course_id, **overrides) -> dict:
    """POST /cohorts — course_id, seat_capacity, starts_at, ends_at, total_sessions."""
    defaults = {
        "course_id": course_id,
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
        "starts_at": DEFAULTS["STARTS_AT"],
        "ends_at": DEFAULTS["ENDS_AT"],
        "total_sessions": DEFAULTS["TOTAL_SESSIONS"],
    }
    defaults.update(overrides)
    return defaults


def register_student_payload(**overrides) -> dict:
    """POST /students/register — email, full_name."""
    defaults = {
        "email": "student@example.com",
        "full_name": "Test Student",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, cohort_id, expected_cohort_version, **overrides) -> dict:
    """POST /enrollments — student_id, cohort_id, expected_cohort_version, optional coupon_code."""
    defaults = {
        "student_id": student_id,
        "cohort_id": cohort_id,
        "expected_cohort_version": expected_cohort_version,
    }
    defaults.update(overrides)
    return defaults


def create_practice_attempt_payload(enrollment_id, attempt_type, raw_correct, total_items, **overrides) -> dict:
    """POST /practice-attempts — enrollment_id, attempt_type, raw_correct, total_items."""
    defaults = {
        "enrollment_id": enrollment_id,
        "attempt_type": attempt_type,
        "raw_correct": raw_correct,
        "total_items": total_items,
    }
    defaults.update(overrides)
    return defaults


def create_installment_plan_payload(enrollment_id, num_installments, **overrides) -> dict:
    """POST /installment-plans — enrollment_id, num_installments."""
    defaults = {
        "enrollment_id": enrollment_id,
        "num_installments": num_installments,
    }
    defaults.update(overrides)
    return defaults


def create_guarantee_claim_payload(enrollment_id, resolution, **overrides) -> dict:
    """POST /guarantee-claims — enrollment_id, resolution."""
    defaults = {
        "enrollment_id": enrollment_id,
        "resolution": resolution,
    }
    defaults.update(overrides)
    return defaults
