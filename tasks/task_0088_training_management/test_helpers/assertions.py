"""Entity assertions and domain invariant checkers.

Per PRD §2.4: CourseCategory, Course, Instructor, Session, Classroom,
OnlineRoom, Enrollment, Trainee, CreditPool, CertificateTemplate,
Certificate carry id/created_at/updated_at/version. CourseVersion,
InstructorAvailability, CheckIn, ExamAttempt, EvaluationSurvey,
CreditAdjustment, SyncEvent, AuditLog are append-only and carry only
id + created_at; the helpers below enforce that distinction.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers
# ---------------------------------------------------------------------------
def _assert_mutable_common(data: dict, entity_label: str) -> None:
    """Assert id/created_at/updated_at/version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_label}.version must be integer, got {type(data.get('version'))}"
    )
    assert data["version"] >= 0, (
        f"{entity_label}.version must be non-negative, got {data['version']}"
    )


def _assert_append_only_common(data: dict, entity_label: str) -> None:
    """Assert id + created_at for append-only rows; PRD §2.4 forbids
    updated_at and version on these entities."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# CourseCategory
# ---------------------------------------------------------------------------
def assert_course_category(data: dict) -> None:
    _assert_mutable_common(data, "CourseCategory")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    # PRD §3.1: parent_id is nullable for roots.
    parent = data.get("parent_id")
    if parent is not None:
        assert isinstance(parent, str)
    # PRD §3.1: depth is 0..4.
    assert isinstance(data["depth"], int)
    assert 0 <= data["depth"] <= 4
    assert isinstance(data["course_count"], int)
    assert data["course_count"] >= 0


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------
def assert_course(data: dict) -> None:
    _assert_mutable_common(data, "Course")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert isinstance(data["category_id"], str) and data["category_id"]
    assert isinstance(data["objective"], str)
    assert isinstance(data["outline"], str)
    assert isinstance(data["duration_hours"], (int, float))
    assert 0.5 <= float(data["duration_hours"]) <= 40.0
    assert isinstance(data["credit_value"], (int, float))
    assert 0.0 <= float(data["credit_value"]) <= 20.0
    assert data["status"] in (
        "DRAFT", "PENDING_REVIEW", "ON_SHELF", "OFF_SHELF", "ARCHIVED",
    )
    assert isinstance(data["current_version_no"], int)
    assert data["current_version_no"] >= 0
    assert isinstance(data["is_charged"], bool)
    assert isinstance(data["prerequisite_course_ids"], list)
    assert isinstance(data["tags"], list)


# ---------------------------------------------------------------------------
# CourseVersion (append-only)
# ---------------------------------------------------------------------------
def assert_course_version(data: dict) -> None:
    _assert_append_only_common(data, "CourseVersion")
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "CourseVersion must NOT carry updated_at (PRD §2.4)"
    )
    assert "version" not in data or data.get("version") is None, (
        "CourseVersion must NOT carry version (PRD §2.4)"
    )
    assert isinstance(data["course_id"], str)
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["snapshot"], dict)


# ---------------------------------------------------------------------------
# Instructor
# ---------------------------------------------------------------------------
def assert_instructor(data: dict) -> None:
    _assert_mutable_common(data, "Instructor")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["instructor_type"] in ("INTERNAL", "EXTERNAL")
    assert isinstance(data["expertise_tags"], list)
    assert isinstance(data["qualifications"], list)
    assert isinstance(data["hourly_rate"], (int, float))
    assert float(data["hourly_rate"]) >= 0
    assert isinstance(data["travel_cost"], (int, float))
    assert float(data["travel_cost"]) >= 0
    assert data["status"] in ("ACTIVE", "BLACKLISTED", "RETIRED")
    # PRD §3.2: INTERNAL hourly_rate == 0 and travel_cost == 0.
    if data["instructor_type"] == "INTERNAL":
        assert float(data["hourly_rate"]) == 0.0, (
            f"INTERNAL instructor must have hourly_rate=0, got {data['hourly_rate']}"
        )
        assert float(data["travel_cost"]) == 0.0, (
            f"INTERNAL instructor must have travel_cost=0, got {data['travel_cost']}"
        )


# ---------------------------------------------------------------------------
# InstructorAvailability (append-only)
# ---------------------------------------------------------------------------
def assert_instructor_availability(data: dict) -> None:
    _assert_append_only_common(data, "InstructorAvailability")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert isinstance(data["instructor_id"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["kind"] in ("AVAILABLE", "BLOCKED")


# ---------------------------------------------------------------------------
# Classroom / OnlineRoom
# ---------------------------------------------------------------------------
def assert_classroom(data: dict) -> None:
    _assert_mutable_common(data, "Classroom")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] in ("ACTIVE", "MAINTENANCE", "RETIRED")
    assert isinstance(data["setup_buffer_minutes"], int)
    assert 0 <= data["setup_buffer_minutes"] <= 240


def assert_online_room(data: dict) -> None:
    _assert_mutable_common(data, "OnlineRoom")
    assert isinstance(data["platform"], str) and data["platform"]
    assert isinstance(data["join_url"], str) and data["join_url"]
    assert isinstance(data["max_participants"], int)
    assert data["max_participants"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
def assert_session(data: dict) -> None:
    _assert_mutable_common(data, "Session")
    assert isinstance(data["course_id"], str)
    assert isinstance(data["instructor_id"], str)
    assert data["mode"] in ("ONSITE", "ONLINE", "HYBRID")
    # PRD §3.3: ONSITE requires classroom_id, forbids online_room_id;
    # ONLINE requires online_room_id, forbids classroom_id; HYBRID
    # requires both.
    classroom_id = data.get("classroom_id")
    online_room_id = data.get("online_room_id")
    if data["mode"] == "ONSITE":
        assert classroom_id, "ONSITE session must carry classroom_id"
        assert not online_room_id, (
            "ONSITE session must NOT carry online_room_id"
        )
    elif data["mode"] == "ONLINE":
        assert online_room_id, "ONLINE session must carry online_room_id"
        assert not classroom_id, "ONLINE session must NOT carry classroom_id"
    elif data["mode"] == "HYBRID":
        assert classroom_id and online_room_id, (
            "HYBRID session must carry both classroom_id and online_room_id"
        )
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert is_iso8601_timestamp(data["enrollment_deadline"])
    assert isinstance(data["capacity"], int) and 1 <= data["capacity"] <= 500
    assert isinstance(data["waitlist_capacity"], int)
    assert 0 <= data["waitlist_capacity"] <= 100
    assert data["status"] in (
        "SCHEDULED", "ENROLLMENT_OPEN", "ENROLLMENT_CLOSED",
        "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["enrolled_count"], int)
    assert data["enrolled_count"] >= 0
    assert isinstance(data["waitlist_count"], int)
    assert data["waitlist_count"] >= 0
    assert isinstance(data["cancellation_fee_charged"], bool)
    # PRD §3.3: pinned_course_version_id is server-minted at creation.
    assert isinstance(data["pinned_course_version_id"], str)
    assert data["pinned_course_version_id"]


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
def assert_enrollment(data: dict) -> None:
    _assert_mutable_common(data, "Enrollment")
    assert isinstance(data["session_id"], str)
    assert isinstance(data["trainee_id"], str)
    assert data["mode"] in ("SELF", "ASSIGNED")
    assert data["status"] in (
        "PENDING_APPROVAL", "CONFIRMED", "WAITLISTED",
        "CANCELLED", "NO_SHOW", "COMPLETED", "FAILED",
    )
    if data["status"] == "WAITLISTED":
        assert isinstance(data.get("waitlist_position"), int)
        assert data["waitlist_position"] >= 1
    else:
        # PRD §1.1: waitlist_position is null when status != WAITLISTED.
        wp = data.get("waitlist_position")
        assert wp is None or wp == 0 or wp == "" or wp is False, (
            f"Enrollment.waitlist_position must be null when "
            f"status={data['status']}, got {wp!r}"
        )
    assert data["attendance_status"] in (
        "NOT_RECORDED", "PRESENT", "ABSENT", "PARTIAL",
    )
    assert isinstance(data["provisional_credit"], (int, float))
    assert isinstance(data["final_credit"], (int, float))


# ---------------------------------------------------------------------------
# Trainee
# ---------------------------------------------------------------------------
def assert_trainee(data: dict) -> None:
    _assert_mutable_common(data, "Trainee")
    assert isinstance(data["employee_no"], str) and data["employee_no"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["department"], str)
    assert isinstance(data["job_level"], int)
    assert 1 <= data["job_level"] <= 15
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "OFFBOARDED")


# ---------------------------------------------------------------------------
# CheckIn (append-only)
# ---------------------------------------------------------------------------
def assert_check_in(data: dict) -> None:
    _assert_append_only_common(data, "CheckIn")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert isinstance(data["session_id"], str)
    assert isinstance(data["enrollment_id"], str)
    assert data["channel"] in ("QR", "FACE", "IP_RANGE")
    assert isinstance(data["source_value"], str)
    assert is_iso8601_timestamp(data["checked_in_at"])


# ---------------------------------------------------------------------------
# ExamAttempt (append-only)
# ---------------------------------------------------------------------------
def assert_exam_attempt(data: dict) -> None:
    _assert_append_only_common(data, "ExamAttempt")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["questions"], list) and data["questions"]
    assert isinstance(data["total_weight"], int)
    assert data["total_weight"] >= 1
    assert isinstance(data["score"], (int, float))
    assert 0.0 <= float(data["score"]) <= 100.0
    assert isinstance(data["passed"], bool)


# ---------------------------------------------------------------------------
# EvaluationSurvey (append-only)
# ---------------------------------------------------------------------------
def assert_evaluation_survey(data: dict) -> None:
    _assert_append_only_common(data, "EvaluationSurvey")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert isinstance(data["enrollment_id"], str)
    for f in ("content_score", "instructor_score", "logistics_score"):
        v = data[f]
        assert isinstance(v, int) and 1 <= v <= 5, (
            f"EvaluationSurvey.{f} must be 1..5, got {v!r}"
        )
    assert isinstance(data["aggregate_score"], (int, float))


# ---------------------------------------------------------------------------
# CreditPool
# ---------------------------------------------------------------------------
def assert_credit_pool(data: dict) -> None:
    _assert_mutable_common(data, "CreditPool")
    assert isinstance(data["trainee_id"], str)
    assert data["cycle_kind"] in ("ANNUAL", "BIENNIAL")
    assert is_iso8601_timestamp(data["cycle_start"])
    assert is_iso8601_timestamp(data["cycle_end"])
    assert isinstance(data["required_credits"], (int, float))
    assert float(data["required_credits"]) >= 0
    assert isinstance(data["accumulated_credits"], (int, float))
    assert isinstance(data["shortfall_warning_emitted"], bool)


# ---------------------------------------------------------------------------
# CreditAdjustment (append-only)
# ---------------------------------------------------------------------------
def assert_credit_adjustment(data: dict) -> None:
    _assert_append_only_common(data, "CreditAdjustment")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert isinstance(data["credit_pool_id"], str)
    assert isinstance(data["delta"], (int, float))
    assert isinstance(data["reason"], str) and data["reason"]
    assert isinstance(data["actor_role"], str)


# ---------------------------------------------------------------------------
# CertificateTemplate
# ---------------------------------------------------------------------------
def assert_certificate_template(data: dict) -> None:
    _assert_mutable_common(data, "CertificateTemplate")
    assert isinstance(data["course_id"], str)
    assert isinstance(data["validity_months"], int)
    assert 1 <= data["validity_months"] <= 120
    assert isinstance(data["renewal_window_days"], int)
    assert 1 <= data["renewal_window_days"] <= 180
    assert isinstance(data["requires_attendance"], bool)
    assert isinstance(data["requires_exam_pass"], bool)


# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------
def assert_certificate(data: dict) -> None:
    _assert_mutable_common(data, "Certificate")
    assert isinstance(data["trainee_id"], str)
    assert isinstance(data["certificate_template_id"], str)
    assert isinstance(data["source_enrollment_id"], str)
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in (
        "VALID", "EXPIRING_SOON", "EXPIRED", "REVOKED", "RENEWED",
    )
    assert isinstance(data["verification_code"], str)
    assert data["verification_code"]


# ---------------------------------------------------------------------------
# SyncEvent (append-only)
# ---------------------------------------------------------------------------
def assert_sync_event(data: dict) -> None:
    _assert_append_only_common(data, "SyncEvent")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert data["source_system"] in ("HR", "IM", "LCP")
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert data["outcome"] in ("PENDING", "APPLIED", "REJECTED")


# ---------------------------------------------------------------------------
# AuditLog (append-only)
# ---------------------------------------------------------------------------
def assert_audit_log(data: dict) -> None:
    _assert_append_only_common(data, "AuditLog")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    # PRD §3.8: subject_kind is one of ENROLLMENT or CREDIT_POOL.
    assert data["subject_kind"] in ("ENROLLMENT", "CREDIT_POOL")
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["action"], str) and data["action"]


# ---------------------------------------------------------------------------
# Helpers used by tests
# ---------------------------------------------------------------------------
def find_row(rows: Iterable[dict], **predicates) -> Optional[dict]:
    """Return the first row matching all predicate fields, else None."""
    for row in rows:
        if all(row.get(k) == v for k, v in predicates.items()):
            return row
    return None


def select_rows(rows: Iterable[dict], **predicates) -> List[dict]:
    return [r for r in rows if all(r.get(k) == v for k, v in predicates.items())]


def assert_updated_at_advanced(before: dict, after: dict) -> None:
    """PRD §2.4: updated_at advances on every mutation."""
    assert after["updated_at"] > before["updated_at"], (
        f"updated_at must advance: before={before['updated_at']!r}, "
        f"after={after['updated_at']!r}"
    )


def assert_version_increases(before: dict, after: dict) -> None:
    """PRD §2.4: version increments by one with every mutation."""
    assert after["version"] == before["version"] + 1, (
        f"version must increment by 1: before={before['version']}, "
        f"after={after['version']}"
    )


__all__ = [
    "assert_course_category",
    "assert_course",
    "assert_course_version",
    "assert_instructor",
    "assert_instructor_availability",
    "assert_classroom",
    "assert_online_room",
    "assert_session",
    "assert_enrollment",
    "assert_trainee",
    "assert_check_in",
    "assert_exam_attempt",
    "assert_evaluation_survey",
    "assert_credit_pool",
    "assert_credit_adjustment",
    "assert_certificate_template",
    "assert_certificate",
    "assert_sync_event",
    "assert_audit_log",
    "find_row",
    "select_rows",
    "assert_updated_at_advanced",
    "assert_version_increases",
]
