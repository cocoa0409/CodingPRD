"""Resource lookups that raise ApiError on missing."""
from __future__ import annotations

from typing import Any

from ..errors import ApiError
from ..store import get_store


def get_course_category(cid: str) -> dict[str, Any]:
    store = get_store()
    row = store.course_categories.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"CourseCategory {cid} not found.")
    return row


def get_course(cid: str) -> dict[str, Any]:
    row = get_store().courses.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Course {cid} not found.")
    return row


def get_instructor(cid: str) -> dict[str, Any]:
    row = get_store().instructors.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Instructor {cid} not found.")
    return row


def get_classroom(cid: str) -> dict[str, Any]:
    row = get_store().classrooms.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Classroom {cid} not found.")
    return row


def get_online_room(cid: str) -> dict[str, Any]:
    row = get_store().online_rooms.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"OnlineRoom {cid} not found.")
    return row


def get_session(cid: str) -> dict[str, Any]:
    row = get_store().sessions.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Session {cid} not found.")
    return row


def get_enrollment(cid: str) -> dict[str, Any]:
    row = get_store().enrollments.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Enrollment {cid} not found.")
    return row


def get_trainee(cid: str) -> dict[str, Any]:
    row = get_store().trainees.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Trainee {cid} not found.")
    return row


def get_exam_attempt(cid: str) -> dict[str, Any]:
    row = get_store().exam_attempts.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"ExamAttempt {cid} not found.")
    return row


def get_credit_pool(cid: str) -> dict[str, Any]:
    row = get_store().credit_pools.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"CreditPool {cid} not found.")
    return row


def get_certificate(cid: str) -> dict[str, Any]:
    row = get_store().certificates.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Certificate {cid} not found.")
    return row


def get_certificate_template_by_course(course_id: str) -> dict[str, Any] | None:
    store = get_store()
    tpl_id = store.cert_template_by_course.get(course_id)
    if not tpl_id:
        return None
    return store.certificate_templates.get(tpl_id)


def get_course_version(cid: str) -> dict[str, Any]:
    row = get_store().course_versions.get(cid)
    if not row:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"CourseVersion {cid} not found.")
    return row


# Reference-not-found variants (422)


def ref_course(cid: str) -> dict[str, Any]:
    row = get_store().courses.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Course {cid} referenced but not found.")
    return row


def ref_category(cid: str) -> dict[str, Any]:
    row = get_store().course_categories.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"CourseCategory {cid} referenced but not found.")
    return row


def ref_instructor(cid: str) -> dict[str, Any]:
    row = get_store().instructors.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Instructor {cid} referenced but not found.")
    return row


def ref_classroom(cid: str) -> dict[str, Any]:
    row = get_store().classrooms.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Classroom {cid} referenced but not found.")
    return row


def ref_online_room(cid: str) -> dict[str, Any]:
    row = get_store().online_rooms.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"OnlineRoom {cid} referenced but not found.")
    return row


def ref_session(cid: str) -> dict[str, Any]:
    row = get_store().sessions.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Session {cid} referenced but not found.")
    return row


def ref_trainee(cid: str) -> dict[str, Any]:
    row = get_store().trainees.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Trainee {cid} referenced but not found.")
    return row


def ref_enrollment(cid: str) -> dict[str, Any]:
    row = get_store().enrollments.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Enrollment {cid} referenced but not found.")
    return row


def ref_credit_pool(cid: str) -> dict[str, Any]:
    row = get_store().credit_pools.get(cid)
    if not row:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"CreditPool {cid} referenced but not found.")
    return row
