"""Path-segment validation and OCC helpers."""

from .errors import APIError
from .store import (
    DISTRICTS, STUDENTS, EVALUATIONS, CONSENTS, IEPS, GOALS,
    SERVICES, SESSIONS, TRANSITION_PLANS, PROGRESS_REPORTS,
)


def get_district(district_id: str) -> dict:
    d = DISTRICTS.get(district_id)
    if d is None:
        raise APIError("ERR_DISTRICT_NOT_FOUND", f"District {district_id} not found.")
    return d


def get_student(district_id: str, student_id: str) -> dict:
    get_district(district_id)
    s = STUDENTS.get(student_id)
    if s is None or s.get("district_id") != district_id:
        raise APIError("ERR_STUDENT_NOT_FOUND", f"Student {student_id} not found.")
    return s


def get_evaluation(district_id: str, student_id: str, evaluation_id: str) -> dict:
    get_student(district_id, student_id)
    e = EVALUATIONS.get(evaluation_id)
    if e is None or e.get("student_id") != student_id or e.get("district_id") != district_id:
        raise APIError("ERR_EVALUATION_NOT_FOUND", f"Evaluation {evaluation_id} not found.")
    return e


def get_consent(district_id: str, student_id: str, consent_id: str) -> dict:
    get_student(district_id, student_id)
    c = CONSENTS.get(consent_id)
    if c is None or c.get("student_id") != student_id or c.get("district_id") != district_id:
        raise APIError("ERR_CONSENT_NOT_FOUND", f"Consent {consent_id} not found.")
    return c


def get_iep(district_id: str, student_id: str, iep_id: str) -> dict:
    get_student(district_id, student_id)
    i = IEPS.get(iep_id)
    if i is None or i.get("student_id") != student_id or i.get("district_id") != district_id:
        raise APIError("ERR_IEP_NOT_FOUND", f"IEP {iep_id} not found.")
    return i


def get_goal(district_id: str, student_id: str, iep_id: str, goal_id: str) -> dict:
    get_iep(district_id, student_id, iep_id)
    g = GOALS.get(goal_id)
    if g is None or g.get("iep_id") != iep_id or g.get("student_id") != student_id:
        raise APIError("ERR_GOAL_NOT_FOUND", f"Goal {goal_id} not found.")
    return g


def get_service(district_id: str, student_id: str, iep_id: str, service_id: str) -> dict:
    get_iep(district_id, student_id, iep_id)
    s = SERVICES.get(service_id)
    if s is None or s.get("iep_id") != iep_id or s.get("student_id") != student_id:
        raise APIError("ERR_SERVICE_NOT_FOUND", f"Service {service_id} not found.")
    return s


def get_session(district_id: str, student_id: str, iep_id: str, service_id: str, session_id: str) -> dict:
    get_service(district_id, student_id, iep_id, service_id)
    ses = SESSIONS.get(session_id)
    if ses is None or ses.get("related_service_id") != service_id or ses.get("iep_id") != iep_id:
        raise APIError("ERR_SESSION_NOT_FOUND", f"Session {session_id} not found.")
    return ses


def check_version(provided, current_version: int) -> None:
    """Compare the optional `version` from a mutation body against the stored value.

    If the field is missing/None, skip the check. Mismatch raises ERR_VERSION_MISMATCH.
    """
    if provided is None:
        return
    if not isinstance(provided, int) or provided != current_version:
        raise APIError("ERR_VERSION_MISMATCH", "Provided version does not match the current value.")


def require_json_body() -> dict:
    """Return the JSON body, or {}. Raise ERR_INVALID_REQUEST on malformed JSON."""
    from flask import request

    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise APIError("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return body
