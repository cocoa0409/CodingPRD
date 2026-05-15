"""Entity serializers — produce stable JSON payloads."""
from __future__ import annotations

from typing import Any


def _copy(d: dict[str, Any]) -> dict[str, Any]:
    return dict(d)


def serialize_course_category(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_course(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_course_version(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_instructor(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_instructor_availability(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_classroom(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_online_room(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_session(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_enrollment(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_trainee(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_check_in(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_exam_attempt(row: dict[str, Any]) -> dict[str, Any]:
    # Avoid leaking correct_answer in questions? PRD does not specify hiding; keep as-is.
    return _copy(row)


def serialize_evaluation(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_credit_pool(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_credit_adjustment(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_certificate_template(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_certificate(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_sync_event(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)


def serialize_audit_log(row: dict[str, Any]) -> dict[str, Any]:
    return _copy(row)
