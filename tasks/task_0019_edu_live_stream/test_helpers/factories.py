"""Payload factories — one per entity, input-only fields per PRD §3 and §4.

Each factory returns the exact PRD-named field set. Tests pass **overrides to
control individual values; defaults fill in the rest with sensible values that
satisfy the PRD's syntactic constraints (positive durations, valid enum
values, in-range pricing).
"""

import uuid
from typing import Any, Dict, List, Optional


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


# ─────────────────── Course ───────────────────

def create_course_payload(instructor_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /courses — Instructor creates a course (PRD §3.1).

    Required: title, instructor_id, list_price_cents.
    Optional: discount_percent (default 0).
    """
    defaults: Dict[str, Any] = {
        "title": f"Course {_unique_suffix()}",
        "instructor_id": instructor_id,
        "list_price_cents": 100000,
        "discount_percent": 0,
    }
    defaults.update(overrides)
    return defaults


def patch_course_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /courses/{id} — partial update of title or pricing (PRD §3.1).

    Caller supplies exactly the fields they want to update.
    """
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ─────────────────── Chapter ───────────────────

def create_chapter_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /courses/{id}/chapters (PRD §3.1).

    Required: title, ordinal, video_duration_seconds (>0).
    Optional: required_for_completion (default true).
    """
    defaults: Dict[str, Any] = {
        "title": f"Chapter {_unique_suffix()}",
        "ordinal": 1,
        "video_duration_seconds": 1000,
        "required_for_completion": True,
    }
    defaults.update(overrides)
    return defaults


# ─────────────────── Instructor ───────────────────

def create_instructor_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /instructors (PRD §3.2).

    Required: display_name, email (unique), bio, availability_windows.
    """
    defaults: Dict[str, Any] = {
        "display_name": f"Instructor {_unique_suffix()}",
        "email": f"i_{_unique_suffix()}@example.com",
        "bio": "Test instructor bio.",
        "availability_windows": [{"start_ts": 0, "end_ts": 10_000_000_000}],
    }
    defaults.update(overrides)
    return defaults


def patch_instructor_availability_payload(windows: List[Dict[str, int]], **overrides: Any) -> Dict[str, Any]:
    """PATCH /instructors/{id}/availability — replace the entire array (PRD §3.2)."""
    payload: Dict[str, Any] = {"availability_windows": windows}
    payload.update(overrides)
    return payload


# ─────────────────── Student ───────────────────

def create_student_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /students (PRD §3.2). Required: display_name, email."""
    defaults: Dict[str, Any] = {
        "display_name": f"Student {_unique_suffix()}",
        "email": f"s_{_unique_suffix()}@example.com",
    }
    defaults.update(overrides)
    return defaults


# ─────────────────── Enrollment ───────────────────

def create_enrollment_payload(student_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /courses/{id}/enrollments (PRD §3.2). Required: student_id."""
    defaults: Dict[str, Any] = {"student_id": student_id}
    defaults.update(overrides)
    return defaults


# ─────────────────── Class group + announcement ───────────────────

def create_class_group_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /courses/{id}/class-groups (PRD §3.2).

    Required: name, capacity (>0). Optional: ta_instructor_id.
    """
    defaults: Dict[str, Any] = {
        "name": f"Cohort-{_unique_suffix()}",
        "capacity": 50,
    }
    defaults.update(overrides)
    return defaults


def assign_enrollment_payload(enrollment_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /class-groups/{id}/assign-enrollment (PRD §3.2). Required: enrollment_id."""
    defaults: Dict[str, Any] = {"enrollment_id": enrollment_id}
    defaults.update(overrides)
    return defaults


def create_announcement_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /class-groups/{id}/announcements (PRD §3.2). Required: body (non-empty)."""
    defaults: Dict[str, Any] = {"body": "Class meets at 10am tomorrow."}
    defaults.update(overrides)
    return defaults


# ─────────────────── Live class ───────────────────

def create_live_class_payload(
    instructor_id: str,
    room_id: str,
    start_ts: int,
    end_ts: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /courses/{id}/live-classes (PRD §3.3).

    Required: instructor_id, room_id, start_ts, end_ts (> start_ts).
    Optional: chapter_id (default null), recording_playback_enabled (default true).
    """
    defaults: Dict[str, Any] = {
        "instructor_id": instructor_id,
        "room_id": room_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "chapter_id": None,
        "recording_playback_enabled": True,
    }
    defaults.update(overrides)
    return defaults


def reschedule_live_class_payload(
    room_id: str, start_ts: int, end_ts: int, **overrides: Any
) -> Dict[str, Any]:
    """POST /live-classes/{id}/reschedule (PRD §3.3). Required: room_id, start_ts, end_ts."""
    defaults: Dict[str, Any] = {"room_id": room_id, "start_ts": start_ts, "end_ts": end_ts}
    defaults.update(overrides)
    return defaults


def checkin_payload(
    checkin_method: str = "TIME_WINDOW",
    checkin_ts: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /live-classes/{id}/check-in (PRD §3.3).

    Required: checkin_method, checkin_ts (null only when mark would be ABSENT/EXCUSED).
    Optional: code_provided (only when checkin_method == CODE).
    """
    defaults: Dict[str, Any] = {
        "checkin_method": checkin_method,
        "checkin_ts": checkin_ts,
    }
    defaults.update(overrides)
    return defaults


# ─────────────────── Leave ───────────────────

def create_leave_request_payload(
    enrollment_id: str, live_class_id: str, **overrides: Any
) -> Dict[str, Any]:
    """POST /leave-requests (PRD §3.3). Required: enrollment_id, live_class_id, reason (non-empty)."""
    defaults: Dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "live_class_id": live_class_id,
        "reason": "Medical appointment.",
    }
    defaults.update(overrides)
    return defaults


# ─────────────────── Assignment + submission ───────────────────

def create_assignment_payload(
    title: str = "Test Assignment",
    fmt: str = "TEXT",
    due_ts: int = 99_999_999_999,
    max_score: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /courses/{id}/assignments (PRD §3.8).

    Required: title, format, due_ts, max_score (>0).
    Optional: chapter_id (default null).
    """
    defaults: Dict[str, Any] = {
        "title": title,
        "format": fmt,
        "due_ts": due_ts,
        "max_score": max_score,
        "chapter_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(enrollment_id: str, fmt: str = "TEXT", **overrides: Any) -> Dict[str, Any]:
    """POST /assignments/{id}/submissions (PRD §3.8).

    Required: enrollment_id and exactly one payload field matching Assignment.format.
    """
    defaults: Dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "payload_text": None,
        "payload_file_url": None,
        "payload_code": None,
    }
    if fmt == "TEXT":
        defaults["payload_text"] = "My submission text."
    elif fmt == "FILE":
        defaults["payload_file_url"] = "https://example.com/sub.pdf"
    elif fmt == "CODE":
        defaults["payload_code"] = "print('hello')"
    defaults.update(overrides)
    return defaults


def update_submission_payload(fmt: str = "TEXT", **overrides: Any) -> Dict[str, Any]:
    """PUT /submissions/{id}/payload (PRD §3.8). Required: payload field matching format."""
    defaults: Dict[str, Any] = {
        "payload_text": None,
        "payload_file_url": None,
        "payload_code": None,
    }
    if fmt == "TEXT":
        defaults["payload_text"] = "My revised submission v2."
    elif fmt == "FILE":
        defaults["payload_file_url"] = "https://example.com/sub_v2.pdf"
    elif fmt == "CODE":
        defaults["payload_code"] = "print('hello v2')"
    defaults.update(overrides)
    return defaults


def request_revision_payload(feedback: str = "Please revise section 2.", **overrides: Any) -> Dict[str, Any]:
    """POST /submissions/{id}/request-revision (PRD §3.8). Required: feedback (non-empty)."""
    defaults: Dict[str, Any] = {"feedback": feedback}
    defaults.update(overrides)
    return defaults


def grade_submission_payload(
    score: int = 80, feedback: str = "Good work overall.", **overrides: Any
) -> Dict[str, Any]:
    """POST /submissions/{id}/grade (PRD §3.8).

    Required: score in [0, max_score], feedback (non-empty).
    Optional: override_plagiarism (boolean).
    """
    defaults: Dict[str, Any] = {"score": score, "feedback": feedback}
    defaults.update(overrides)
    return defaults


# ─────────────────── Watch session ───────────────────

def create_watch_session_payload(chapter_id: str, seconds_watched: int, **overrides: Any) -> Dict[str, Any]:
    """POST /enrollments/{id}/watch-sessions (PRD §3.4). Required: chapter_id, seconds_watched (>0)."""
    defaults: Dict[str, Any] = {"chapter_id": chapter_id, "seconds_watched": seconds_watched}
    defaults.update(overrides)
    return defaults


# ─────────────────── Refund ───────────────────

def create_refund_request_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /enrollments/{id}/refund-requests (PRD §3.7).

    Optional: materials_kit_count (default 0).
    """
    defaults: Dict[str, Any] = {"materials_kit_count": 0}
    defaults.update(overrides)
    return defaults


def reject_refund_request_payload(reason: str = "Not eligible per policy.", **overrides: Any) -> Dict[str, Any]:
    """POST /refund-requests/{id}/reject (PRD §3.7). Required: rejection_reason (non-empty)."""
    defaults: Dict[str, Any] = {"rejection_reason": reason}
    defaults.update(overrides)
    return defaults
