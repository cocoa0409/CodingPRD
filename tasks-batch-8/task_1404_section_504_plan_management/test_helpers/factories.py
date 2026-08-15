"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "SCHOOL_NAME": "Lincoln High",
    "DISTRICT_CODE": "D01",
    "ACADEMIC_YEAR": "2025-2026",
    "STUDENT_DOB": "2012-01-01T00:00:00Z",
    "GRADE_LEVEL": 8,
    "REFERRAL_REASON": "Teacher observes attention difficulty",
    "DISABILITY_CATEGORY": "LEARNING",
    "ACCOMMODATION_TYPE": "EXTENDED_TIME",
    "ACCOMMODATION_DESCRIPTION": "1.5x time on assessments",
    "PARENT_REF": "parent-1",
    "GRIEVANCE_CATEGORY": "NON_IMPLEMENTATION",
    "GRIEVANCE_DESCRIPTION": "Accommodation not delivered",
    "TRAINING_TOPIC": "SECTION_504_BASICS",
    "REVIEW_TYPE": "ANNUAL",
    "TEST_NAME": "State ELA Grade 8",
}


def create_school_payload(**overrides) -> dict:
    defaults = {
        "school_name": DEFAULTS["SCHOOL_NAME"],
        "district_code": DEFAULTS["DISTRICT_CODE"],
        "current_academic_year": DEFAULTS["ACADEMIC_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_member_payload(school_id, staff_role, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "staff_external_ref": f"REF-{staff_role}",
        "full_name": f"Staff {staff_role}",
        "staff_role": staff_role,
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(staff_id, trained_at, **overrides) -> dict:
    defaults = {
        "staff_id": staff_id,
        "training_topic": DEFAULTS["TRAINING_TOPIC"],
        "trained_at": trained_at,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(school_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "student_external_ref": "STU-1",
        "full_name": "Student One",
        "date_of_birth": DEFAULTS["STUDENT_DOB"],
        "grade_level": DEFAULTS["GRADE_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "referral_reason": DEFAULTS["REFERRAL_REASON"],
        "suspected_disability_category": DEFAULTS["DISABILITY_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def determine_evaluation_payload(**overrides) -> dict:
    defaults = {
        "determination_outcome": "ELIGIBLE",
        "disability_impairment_found": True,
        "major_life_activity_affected": True,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(student_id, evaluation_id, expected_student_version, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "evaluation_id": evaluation_id,
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


def create_accommodation_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "accommodation_type": DEFAULTS["ACCOMMODATION_TYPE"],
        "description": DEFAULTS["ACCOMMODATION_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_implementation_log_payload(plan_id, accommodation_id, log_date, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "accommodation_id": accommodation_id,
        "log_date": log_date,
        "was_implemented_as_planned": True,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(plan_id, scheduled_for, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "review_type": DEFAULTS["REVIEW_TYPE"],
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


def create_testing_request_payload(plan_id, accommodation_id, test_date, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "accommodation_id": accommodation_id,
        "test_name": DEFAULTS["TEST_NAME"],
        "test_date": test_date,
    }
    defaults.update(overrides)
    return defaults


def create_consent_record_payload(student_id, consent_scope, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "consent_scope": consent_scope,
    }
    defaults.update(overrides)
    return defaults


def consent_response_payload(**overrides) -> dict:
    defaults = {
        "granted": True,
        "responded_by_parent_ref": DEFAULTS["PARENT_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_grievance_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "grievance_category": DEFAULTS["GRIEVANCE_CATEGORY"],
        "description": DEFAULTS["GRIEVANCE_DESCRIPTION"],
        "filed_by_parent_ref": DEFAULTS["PARENT_REF"],
    }
    defaults.update(overrides)
    return defaults
