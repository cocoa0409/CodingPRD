"""Payload factories — one per entity, input fields only.

Each factory supplies exactly the PRD-required input fields plus whatever
optional fields the caller passes as ``**overrides``.  Optional fields with a
declared server-side default are never sent unless a test asks for them, since
the enforcement stack rejects any unknown field and a test that leans on a
default should not be the one sending it.
"""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "STUDENT_NUMBER": "S-0001",
    "FULL_NAME": "Test Student",
    "RACE_ETHNICITY_CODE": "WHITE",
    "COURSE_CODE": "MATH-100",
    "COURSE_TITLE": "College Algebra",
    "SUBJECT_AREA": "MATH",
    "LEVEL_RANK": 100,
    "UNITS": 3.0,
    "VERSION_LABEL": "CS-2026-A",
    "PRIORITY_RANK": 100,
    "JUSTIFICATION": "Instructor judgement supports waiving this requirement.",
    "STATEMENT": "My transcript GPA supports a higher placement.",
    "INFO_REQUEST_NOTE": "Please supply the sending high school transcript.",
    "DECISION_NOTE": "Reviewed on the documentary record.",
}


# --------------------------------------------------------------------------- #
# Students
# --------------------------------------------------------------------------- #
def create_student_payload(**overrides) -> dict:
    payload = {
        "student_number": DEFAULTS["STUDENT_NUMBER"],
        "full_name": DEFAULTS["FULL_NAME"],
        "race_ethnicity_code": DEFAULTS["RACE_ETHNICITY_CODE"],
    }
    payload.update(overrides)
    return payload


def update_measures_payload(**overrides) -> dict:
    """Every field of the measures revision is optional; only supplied fields
    change."""
    payload: dict = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Courses and requisite edges
# --------------------------------------------------------------------------- #
def create_course_payload(**overrides) -> dict:
    payload = {
        "course_code": DEFAULTS["COURSE_CODE"],
        "title": DEFAULTS["COURSE_TITLE"],
        "subject_area": DEFAULTS["SUBJECT_AREA"],
        "level_rank": DEFAULTS["LEVEL_RANK"],
        "units": DEFAULTS["UNITS"],
    }
    payload.update(overrides)
    return payload


def create_course_requisite_payload(course_id, requisite_course_id, **overrides) -> dict:
    payload = {
        "course_id": course_id,
        "requisite_course_id": requisite_course_id,
        "requisite_type": "PREREQUISITE",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Placement rules
# --------------------------------------------------------------------------- #
def create_placement_rule_payload(target_course_id, **overrides) -> dict:
    payload = {
        "subject_area": DEFAULTS["SUBJECT_AREA"],
        "measure_type": "TEST_SCORE",
        "target_course_id": target_course_id,
        "priority_rank": DEFAULTS["PRIORITY_RANK"],
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "version_label": DEFAULTS["VERSION_LABEL"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Test administrations and attempts
# --------------------------------------------------------------------------- #
def create_test_administration_payload(proctor_user_id, **overrides) -> dict:
    payload = {
        "room_code": TEST_DEFAULTS["ROOM_CODE"],
        "subject_area": DEFAULTS["SUBJECT_AREA"],
        "proctor_user_id": proctor_user_id,
        "starts_at": TEST_DEFAULTS["SESSION_STARTS_AT"],
        "ends_at": TEST_DEFAULTS["SESSION_ENDS_AT"],
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_test_attempt_payload(student_id, administration_id, **overrides) -> dict:
    payload = {"student_id": student_id, "administration_id": administration_id}
    payload.update(overrides)
    return payload


def score_attempt_payload(raw_score, **overrides) -> dict:
    payload = {"raw_score": raw_score}
    payload.update(overrides)
    return payload


def void_attempt_payload(void_reason="ADMIN_CORRECTION", **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


def administration_status_payload(target_status, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Determinations
# --------------------------------------------------------------------------- #
def create_determination_payload(
    student_id, expected_student_version, subject_area=None, **overrides
) -> dict:
    payload = {
        "student_id": student_id,
        "subject_area": subject_area or DEFAULTS["SUBJECT_AREA"],
        "expected_student_version": expected_student_version,
    }
    payload.update(overrides)
    return payload


def evidence_payload(target_evidence_state, **overrides) -> dict:
    payload = {"target_evidence_state": target_evidence_state}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Appeals
# --------------------------------------------------------------------------- #
def create_appeal_payload(
    determination_id, requested_course_id, expected_determination_version, **overrides
) -> dict:
    payload = {
        "determination_id": determination_id,
        "requested_course_id": requested_course_id,
        "grounds": "NEW_TRANSCRIPT",
        "statement": DEFAULTS["STATEMENT"],
        "expected_determination_version": expected_determination_version,
    }
    payload.update(overrides)
    return payload


def request_info_payload(info_request_note=None, **overrides) -> dict:
    payload = {"info_request_note": info_request_note or DEFAULTS["INFO_REQUEST_NOTE"]}
    payload.update(overrides)
    return payload


def resubmit_appeal_payload(statement=None, **overrides) -> dict:
    payload = {"statement": statement or DEFAULTS["STATEMENT"]}
    payload.update(overrides)
    return payload


def decide_appeal_payload(decision, decision_note=None, **overrides) -> dict:
    payload = {
        "decision": decision,
        "decision_note": decision_note or DEFAULTS["DECISION_NOTE"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Sections and registrations
# --------------------------------------------------------------------------- #
def create_section_payload(course_id, **overrides) -> dict:
    payload = {
        "course_id": course_id,
        "term_code": TEST_DEFAULTS["TERM_CODE"],
        "room_code": TEST_DEFAULTS["ROOM_CODE"],
        "meets_start_at": TEST_DEFAULTS["MEETS_START_AT"],
        "meets_end_at": TEST_DEFAULTS["MEETS_END_AT"],
        "seat_capacity": TEST_DEFAULTS["SECTION_SEAT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def pair_section_payload(support_section_id, **overrides) -> dict:
    payload = {"support_section_id": support_section_id}
    payload.update(overrides)
    return payload


def section_status_payload(target_status, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def create_registration_payload(
    student_id, section_id, expected_section_version, **overrides
) -> dict:
    payload = {
        "student_id": student_id,
        "section_id": section_id,
        "expected_section_version": expected_section_version,
    }
    payload.update(overrides)
    return payload


def grade_registration_payload(final_grade, **overrides) -> dict:
    payload = {"final_grade": final_grade}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Prerequisite overrides
# --------------------------------------------------------------------------- #
def create_override_payload(student_id, course_id, requisite_id, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "course_id": course_id,
        "requisite_id": requisite_id,
        "justification": DEFAULTS["JUSTIFICATION"],
        "expires_at": TEST_DEFAULTS["OVERRIDE_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Validation studies
# --------------------------------------------------------------------------- #
def create_validation_study_payload(
    candidate_rule_id, window_start_at, window_end_at, **overrides
) -> dict:
    payload = {
        "subject_area": DEFAULTS["SUBJECT_AREA"],
        "candidate_rule_id": candidate_rule_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload


def decide_study_payload(decision, decision_note=None, **overrides) -> dict:
    payload = {
        "decision": decision,
        "decision_note": decision_note or DEFAULTS["DECISION_NOTE"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock_payload(current_utc, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
