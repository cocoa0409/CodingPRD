"""Payload factories — one per write endpoint, input fields only.

Each factory builds a valid default payload and accepts **overrides so a test can
pin exactly the one field it cares about. Only the PRD's input (client-supplied)
fields appear; system/computed fields are never sent.
"""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


# --- Employee --------------------------------------------------------------
def create_employee_payload(**overrides) -> dict:
    payload = {
        "email": f"{_uniq('user')}@example.com",
        "full_name": "Test Employee",
        "department": "ENGINEERING",
        "job_role": "IC",
    }
    payload.update(overrides)
    return payload


# --- Course ----------------------------------------------------------------
def create_course_payload(**overrides) -> dict:
    payload = {
        "code": _uniq("CRS"),
        "title": "Test Course",
        "content_type": "SCORM",
        "passing_score": 70,
    }
    payload.update(overrides)
    return payload


def add_prerequisite_payload(prerequisite_course_id: str, **overrides) -> dict:
    payload = {"prerequisite_course_id": prerequisite_course_id}
    payload.update(overrides)
    return payload


# --- Learning path ---------------------------------------------------------
def create_learning_path_payload(**overrides) -> dict:
    payload = {
        "code": _uniq("LP"),
        "title": "Test Path",
    }
    payload.update(overrides)
    return payload


def add_path_step_payload(course_id: str, sequence_index: int, **overrides) -> dict:
    payload = {
        "course_id": course_id,
        "sequence_index": sequence_index,
    }
    payload.update(overrides)
    return payload


# --- Assignment rule -------------------------------------------------------
def create_assignment_rule_payload(**overrides) -> dict:
    payload = {
        "target_department": "ENGINEERING",
        "target_job_role": "IC",
        "due_in_days": 30,
        "effective_from": "2026-01-01T00:00:00.000Z",
        "effective_to": "2026-12-31T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


# --- Enrollment ------------------------------------------------------------
def create_enrollment_payload(employee_id: str, course_id: str, **overrides) -> dict:
    payload = {
        "employee_id": employee_id,
        "course_id": course_id,
    }
    payload.update(overrides)
    return payload


def quiz_attempt_payload(score: int, expected_enrollment_version: int, **overrides) -> dict:
    payload = {
        "score": score,
        "expected_enrollment_version": expected_enrollment_version,
    }
    payload.update(overrides)
    return payload


# --- Path enrollment -------------------------------------------------------
def create_path_enrollment_payload(employee_id: str, learning_path_id: str, **overrides) -> dict:
    payload = {
        "employee_id": employee_id,
        "learning_path_id": learning_path_id,
    }
    payload.update(overrides)
    return payload


# --- Tracking session ------------------------------------------------------
def commit_session_payload(lesson_status: str, progress_pct: int, **overrides) -> dict:
    payload = {
        "lesson_status": lesson_status,
        "progress_pct": progress_pct,
    }
    payload.update(overrides)
    return payload


# --- Clock -----------------------------------------------------------------
def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
