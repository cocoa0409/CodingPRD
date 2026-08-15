"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from . import constants as C


def create_exam_cycle_payload(**overrides) -> dict:
    defaults = {
        "name": C.TEST_DEFAULTS["CYCLE_NAME"],
        "registration_deadline_at": C.REGISTRATION_DEADLINE_AT,
        "order_deadline_at": C.ORDER_DEADLINE_AT,
        "score_release_at": C.SCORE_RELEASE_AT,
        "exam_window_start_at": C.EXAM_WINDOW_START_AT,
        "exam_window_end_at": C.EXAM_WINDOW_END_AT,
        "late_fee_cents": C.LATE_FEE_CENTS,
        "unused_exam_penalty_cents": C.UNUSED_EXAM_PENALTY_CENTS,
        "fee_reduction_cents": C.FEE_REDUCTION_CENTS,
        "budget_cap_cents": C.BUDGET_CAP_CENTS,
        "rebate_rate_bp": C.REBATE_RATE_BP,
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(cycle_id: str, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "subject_code": C.TEST_DEFAULTS["SUBJECT_CODE"],
        "program": "AP",
        "exam_fee_cents": C.EXAM_FEE_CENTS,
        "credit_threshold": C.CREDIT_THRESHOLD_AP,
    }
    defaults.update(overrides)
    return defaults


def create_teacher_payload(**overrides) -> dict:
    defaults = {
        "full_name": C.TEST_DEFAULTS["TEACHER_NAME"],
        "email": C.TEST_DEFAULTS["TEACHER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_teacher_authorization_payload(teacher_id: str, course_id: str) -> dict:
    return {"teacher_id": teacher_id, "course_id": course_id}


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": C.TEST_DEFAULTS["STUDENT_NAME"],
        "grade_level": 11,
        "subgroup_code": "GEN",
    }
    defaults.update(overrides)
    return defaults


def create_fee_reduction_application_payload(
    student_id: str, cycle_id: str, **overrides
) -> dict:
    defaults = {
        "student_id": student_id,
        "cycle_id": cycle_id,
        "eligibility_basis": "FREE_LUNCH",
        "annual_income_cents": 3_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(student_id: str, course_id: str, **overrides) -> dict:
    payload = {"student_id": student_id, "course_id": course_id}
    payload.update(overrides)
    return payload


def create_exam_order_payload(cycle_id: str) -> dict:
    return {"cycle_id": cycle_id}


def patch_exam_order_payload(expected_version, adjustments=None) -> dict:
    payload = {"expected_exam_order_version": expected_version}
    if adjustments is not None:
        payload["adjustments"] = adjustments
    return payload


def create_exam_session_payload(course_id: str, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "room_name": C.TEST_DEFAULTS["ROOM_NAME"],
        "room_capacity": C.TEST_DEFAULTS["ROOM_CAPACITY"],
        "start_at": C.SESSION_START_AT,
        "end_at": C.SESSION_END_AT,
    }
    defaults.update(overrides)
    return defaults


def administer_session_payload(present_registration_ids) -> dict:
    return {"present_registration_ids": list(present_registration_ids)}


def create_proctor_assignment_payload(session_id: str, teacher_id: str) -> dict:
    return {"session_id": session_id, "teacher_id": teacher_id}


def create_irregularity_report_payload(session_id: str, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "category": "TIMING_ERROR",
        "details": "Section 1 ran 5 minutes short",
    }
    defaults.update(overrides)
    return defaults


def release_scores_payload(scores) -> dict:
    """scores: list of {registration_id, score} pairs."""
    return {"scores": list(scores)}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
