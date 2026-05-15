"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact schema the PRD declares for the request
body (PRD §3.1–§3.8). Tests pass overrides for the values they want
to control.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Utility — ISO 8601 UTC timestamp helper (PRD §2.2: three fractional digits).
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ---------------------------------------------------------------------------
# Course categories (PRD §3.1)
# ---------------------------------------------------------------------------
def create_course_category_payload(
    name: str = "Engineering",
    parent_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    payload.update(overrides)
    return payload


def update_course_category_payload(
    name: Optional[str] = None,
    parent_id: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if parent_id is not None or "parent_id" in overrides:
        # caller may explicitly pass parent_id=None to clear it; preserve None.
        payload["parent_id"] = parent_id
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Courses (PRD §3.1)
# ---------------------------------------------------------------------------
def create_course_payload(
    code: str = "ENG-101",
    title: str = "Introduction to Engineering",
    category_id: str = "",
    objective: str = "Provide a survey of engineering fundamentals.",
    outline: str = "## Outline\n- Topic 1\n- Topic 2",
    duration_hours: float = 4.0,
    credit_value: float = 4.0,
    prerequisite_course_ids: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    is_charged: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "title": title,
        "category_id": category_id,
        "objective": objective,
        "outline": outline,
        "duration_hours": duration_hours,
        "credit_value": credit_value,
        "is_charged": is_charged,
    }
    if prerequisite_course_ids is not None:
        payload["prerequisite_course_ids"] = prerequisite_course_ids
    if tags is not None:
        payload["tags"] = tags
    payload.update(overrides)
    return payload


def update_course_payload(
    version: Optional[int] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """All editable fields (title, objective, outline, duration_hours,
    prerequisite_course_ids, tags, credit_value, is_charged) flow
    through **fields. PRD §3.1 makes `code` immutable."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(fields)
    return payload


# ---------------------------------------------------------------------------
# Instructors (PRD §3.2)
# ---------------------------------------------------------------------------
def create_instructor_payload(
    full_name: str = "Test Instructor",
    instructor_type: str = "EXTERNAL",
    expertise_tags: Optional[List[str]] = None,
    qualifications: Optional[List[str]] = None,
    hourly_rate: float = 200.00,
    travel_cost: float = 50.00,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "instructor_type": instructor_type,
        "hourly_rate": hourly_rate,
        "travel_cost": travel_cost,
    }
    if expertise_tags is not None:
        payload["expertise_tags"] = expertise_tags
    if qualifications is not None:
        payload["qualifications"] = qualifications
    payload.update(overrides)
    return payload


def update_instructor_payload(
    version: Optional[int] = None,
    **fields: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(fields)
    return payload


def blacklist_instructor_payload(
    blacklist_reason: str = "Disciplinary review",
) -> Dict[str, Any]:
    return {"blacklist_reason": blacklist_reason}


def create_instructor_availability_payload(
    start_at: str,
    end_at: str,
    kind: str = "AVAILABLE",
) -> Dict[str, Any]:
    return {"start_at": start_at, "end_at": end_at, "kind": kind}


# ---------------------------------------------------------------------------
# Classrooms / OnlineRooms (PRD §3.3)
# ---------------------------------------------------------------------------
def create_classroom_payload(
    name: str = "Building A Room 101",
    capacity: int = 30,
    setup_buffer_minutes: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "capacity": capacity,
        "setup_buffer_minutes": setup_buffer_minutes,
    }
    payload.update(overrides)
    return payload


def create_online_room_payload(
    platform: str = "zoom",
    join_url: str = "https://zoom.example.com/j/test",
    max_participants: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "platform": platform,
        "join_url": join_url,
        "max_participants": max_participants,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sessions (PRD §3.3)
# ---------------------------------------------------------------------------
def create_session_payload(
    course_id: str,
    instructor_id: str,
    mode: str,
    start_at: str,
    end_at: str,
    enrollment_deadline: str,
    capacity: int = 10,
    waitlist_capacity: int = 5,
    classroom_id: Optional[str] = None,
    online_room_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "course_id": course_id,
        "instructor_id": instructor_id,
        "mode": mode,
        "start_at": start_at,
        "end_at": end_at,
        "enrollment_deadline": enrollment_deadline,
        "capacity": capacity,
        "waitlist_capacity": waitlist_capacity,
    }
    if classroom_id is not None:
        payload["classroom_id"] = classroom_id
    if online_room_id is not None:
        payload["online_room_id"] = online_room_id
    payload.update(overrides)
    return payload


def cancel_session_payload(reason: str = "Operational change") -> Dict[str, Any]:
    return {"reason": reason}


def create_check_in_payload(
    enrollment_id: str,
    channel: str = "QR",
    source_value: str = "qr-token-test",
) -> Dict[str, Any]:
    return {
        "enrollment_id": enrollment_id,
        "channel": channel,
        "source_value": source_value,
    }


# ---------------------------------------------------------------------------
# Enrollments (PRD §3.4)
# ---------------------------------------------------------------------------
def create_enrollment_payload(
    session_id: str,
    trainee_id: str,
    mode: str = "SELF",
) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "trainee_id": trainee_id,
        "mode": mode,
    }


def reject_enrollment_payload(
    reason: str = "Manager rejection",
) -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Exam attempts and evaluations (PRD §3.5)
# ---------------------------------------------------------------------------
def create_exam_attempt_payload(enrollment_id: str) -> Dict[str, Any]:
    return {"enrollment_id": enrollment_id}


def submit_exam_attempt_payload(answers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """PRD §3.5: "The submission step accepts a single body field
    `answers` and requires that this payload include an answer for
    every question in `questions`." Each entry should carry
    {question_id, given_answer}."""
    return {"answers": answers}


def create_evaluation_payload(
    enrollment_id: str,
    content_score: int = 5,
    instructor_score: int = 5,
    logistics_score: int = 5,
) -> Dict[str, Any]:
    return {
        "enrollment_id": enrollment_id,
        "content_score": content_score,
        "instructor_score": instructor_score,
        "logistics_score": logistics_score,
    }


# ---------------------------------------------------------------------------
# Credit pools and adjustments (PRD §2.11, §3.6)
# ---------------------------------------------------------------------------
def create_credit_pool_payload(
    trainee_id: str,
    cycle_kind: str = "ANNUAL",
    cycle_start: str = "2026-01-01T00:00:00.000Z",
    required_credits: float = 20.0,
) -> Dict[str, Any]:
    return {
        "trainee_id": trainee_id,
        "cycle_kind": cycle_kind,
        "cycle_start": cycle_start,
        "required_credits": required_credits,
    }


def create_credit_adjustment_payload(
    credit_pool_id: str,
    delta: float,
    reason: str = "Manual adjustment",
) -> Dict[str, Any]:
    return {
        "credit_pool_id": credit_pool_id,
        "delta": delta,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Certificates (PRD §3.7)
# ---------------------------------------------------------------------------
def create_certificate_template_payload(
    course_id: str,
    validity_months: int = 12,
    renewal_window_days: int = 30,
    requires_attendance: bool = True,
    requires_exam_pass: bool = True,
) -> Dict[str, Any]:
    return {
        "course_id": course_id,
        "validity_months": validity_months,
        "renewal_window_days": renewal_window_days,
        "requires_attendance": requires_attendance,
        "requires_exam_pass": requires_exam_pass,
    }


def renew_certificate_payload(source_enrollment_id: str) -> Dict[str, Any]:
    return {"source_enrollment_id": source_enrollment_id}


def revoke_certificate_payload(
    reason: str = "Administrative revocation",
) -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Trainees (PRD §3.4)
# ---------------------------------------------------------------------------
def create_trainee_payload(
    employee_no: str = "EMP-0001",
    full_name: str = "Test Trainee",
    department: str = "engineering",
    job_level: int = 5,
) -> Dict[str, Any]:
    return {
        "employee_no": employee_no,
        "full_name": full_name,
        "department": department,
        "job_level": job_level,
    }


# ---------------------------------------------------------------------------
# Sync events (PRD §3.8)
# ---------------------------------------------------------------------------
def emit_event_payload(
    source_system: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "source_system": source_system,
        "event_type": event_type,
        "payload": payload or {},
    }


# ---------------------------------------------------------------------------
# Clock advance (PRD §2.10)
# ---------------------------------------------------------------------------
def clock_advance_payload(now: str) -> Dict[str, Any]:
    return {"now": now}


__all__ = [
    "iso_utc",
    "create_course_category_payload",
    "update_course_category_payload",
    "create_course_payload",
    "update_course_payload",
    "create_instructor_payload",
    "update_instructor_payload",
    "blacklist_instructor_payload",
    "create_instructor_availability_payload",
    "create_classroom_payload",
    "create_online_room_payload",
    "create_session_payload",
    "cancel_session_payload",
    "create_check_in_payload",
    "create_enrollment_payload",
    "reject_enrollment_payload",
    "create_exam_attempt_payload",
    "submit_exam_attempt_payload",
    "create_evaluation_payload",
    "create_credit_pool_payload",
    "create_credit_adjustment_payload",
    "create_certificate_template_payload",
    "renew_certificate_payload",
    "revoke_certificate_payload",
    "create_trainee_payload",
    "emit_event_payload",
    "clock_advance_payload",
]
