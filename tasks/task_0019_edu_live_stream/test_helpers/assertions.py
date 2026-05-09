"""Per-entity assertions and domain invariant checkers.

Wraps the framework's generic helpers (is_valid_uuid, is_iso8601_timestamp)
to provide entity-shaped assertions whose field names match the PRD verbatim.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ──────────────────────────────────────────────────────────
# Common-fields helpers
# ──────────────────────────────────────────────────────────

def _assert_common_fields(data: Dict[str, Any]) -> None:
    """For entities with common_fields=true (PRD §2.4): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), \
        f"version must be int, got {type(data.get('version'))}"


def _assert_append_only_common_fields(data: Dict[str, Any]) -> None:
    """For entities with common_fields=false (PRD §2.4): id and created_at only.

    Per PRD §2.4, append-only/immutable rows do NOT carry updated_at or version.
    The implementer is correctly told to omit those fields, so tests must not
    require them.
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')}"


# ──────────────────────────────────────────────────────────
# Course
# ──────────────────────────────────────────────────────────

COURSE_STATUSES = {"DRAFT", "UNDER_REVIEW", "PUBLISHED", "REJECTED", "DELISTED"}
COURSE_POSTURES = {"OPEN", "RESTRICTED", "FROZEN"}


def assert_course(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"], "title must be non-empty string"
    assert is_valid_uuid(data.get("instructor_id", "")), "instructor_id must be valid UUID"
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0, \
        "list_price_cents must be non-negative integer"
    assert isinstance(data["discount_percent"], int) and 0 <= data["discount_percent"] <= 80, \
        "discount_percent must be int in [0,80]"
    assert data["status"] in COURSE_STATUSES, f"status must be in {COURSE_STATUSES}"
    assert data["posture"] in COURSE_POSTURES, f"posture must be in {COURSE_POSTURES}"


# ──────────────────────────────────────────────────────────
# Chapter
# ──────────────────────────────────────────────────────────

def assert_chapter(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("course_id", "")), "course_id must be valid UUID"
    assert isinstance(data["title"], str) and data["title"], "title must be non-empty string"
    assert isinstance(data["ordinal"], int) and data["ordinal"] >= 1, "ordinal must be >= 1"
    assert isinstance(data["video_duration_seconds"], int) and data["video_duration_seconds"] > 0, \
        "video_duration_seconds must be positive integer"
    assert isinstance(data["required_for_completion"], bool)


# ──────────────────────────────────────────────────────────
# Instructor / Student
# ──────────────────────────────────────────────────────────

def assert_instructor(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data.get("availability_windows", []), list)


def assert_student(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]


# ──────────────────────────────────────────────────────────
# Enrollment
# ──────────────────────────────────────────────────────────

PAYMENT_STATUSES = {"PAID", "REFUND_PENDING", "REFUNDED"}
LEARNING_STATUSES = {"ACTIVE", "AT_RISK", "COMPLETED", "WITHDRAWN"}


def assert_enrollment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("course_id", "")), "course_id must be valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be valid UUID"
    assert data["payment_status"] in PAYMENT_STATUSES, f"payment_status must be in {PAYMENT_STATUSES}"
    assert data["learning_status"] in LEARNING_STATUSES, f"learning_status must be in {LEARNING_STATUSES}"
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0
    assert is_iso8601_timestamp(data.get("enrolled_at", ""))
    # Progress fields are numbers in [0, 100], 1-decimal precision per PRD §2.9.
    for field in ("chapter_completion_percent", "watch_duration_percent", "progress_percent"):
        v = data[field]
        assert isinstance(v, (int, float)) and 0 <= v <= 100, f"{field} out of [0,100]: {v}"


# ──────────────────────────────────────────────────────────
# Class group / Announcement
# ──────────────────────────────────────────────────────────

def assert_class_group(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("course_id", "")), "course_id must be valid UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] > 0


def assert_announcement(data: Dict[str, Any]) -> None:
    """Announcement is append-only (PRD §2.4) — id + created_at only."""
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data.get("class_group_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert data["author_role"] in {"INSTRUCTOR", "TEACHING_ASSISTANT"}
    assert isinstance(data["body"], str) and data["body"]


# ──────────────────────────────────────────────────────────
# Live class / Attendance / Leave
# ──────────────────────────────────────────────────────────

LIVE_CLASS_STATUSES = {"SCHEDULED", "LIVE", "ENDED", "CANCELLED", "RESCHEDULED"}


def assert_live_class(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("course_id", ""))
    assert is_valid_uuid(data.get("instructor_id", ""))
    assert isinstance(data["room_id"], str) and data["room_id"]
    assert isinstance(data["start_ts"], int)
    assert isinstance(data["end_ts"], int)
    assert data["end_ts"] > data["start_ts"], "end_ts must be strictly greater than start_ts"
    assert data["status"] in LIVE_CLASS_STATUSES


def assert_attendance(data: Dict[str, Any]) -> None:
    """Attendance is append-only (PRD §2.4) — id + created_at only."""
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data.get("live_class_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["mark"] in {"ATTENDED", "LATE", "ABSENT", "EXCUSED"}
    assert data["checkin_method"] in {"TIME_WINDOW", "CODE", "FACE", "LEAVE"}


def assert_leave_request(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("live_class_id", ""))
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in {"PENDING", "APPROVED", "REJECTED"}


# ──────────────────────────────────────────────────────────
# Assignment / Submission
# ──────────────────────────────────────────────────────────

def assert_assignment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert data["format"] in {"TEXT", "FILE", "CODE"}
    assert isinstance(data["due_ts"], int)
    assert isinstance(data["max_score"], int) and data["max_score"] > 0
    assert data["status"] in {"DRAFT", "PUBLISHED", "CLOSED"}


def assert_submission(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["status"] in {"SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "GRADED"}
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    # plagiarism_score is in [0.0, 1.0]
    p = data.get("plagiarism_score")
    if p is not None:
        assert isinstance(p, (int, float)) and 0.0 <= p <= 1.0, \
            f"plagiarism_score must be in [0,1], got {p}"


# ──────────────────────────────────────────────────────────
# Refund
# ──────────────────────────────────────────────────────────

def assert_refund_request(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert data["status"] in {"PENDING", "APPROVED", "REJECTED"}
    assert isinstance(data["provisional_amount_cents"], int) and data["provisional_amount_cents"] >= 0


# ──────────────────────────────────────────────────────────
# Syllabus revision (append-only — PRD §2.4)
# ──────────────────────────────────────────────────────────

def assert_syllabus_revision(data: Dict[str, Any]) -> None:
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1


# ──────────────────────────────────────────────────────────
# Watch session (append-only — PRD §2.4)
# ──────────────────────────────────────────────────────────

def assert_watch_session(data: Dict[str, Any]) -> None:
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("chapter_id", ""))
    assert isinstance(data["seconds_watched"], int) and data["seconds_watched"] > 0


# ──────────────────────────────────────────────────────────
# Audit log (append-only — PRD §2.4)
# ──────────────────────────────────────────────────────────

def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_common_fields(data)
    assert data["actor_role"] in {"INSTRUCTOR", "TEACHING_ASSISTANT", "STUDENT", "ACADEMIC_ADMIN"}
    assert data["action"] in {
        "ENROLLMENT_CREATED", "ENROLLMENT_GROUPED", "ENROLLMENT_WITHDRAWN",
        "REFUND_REQUESTED", "REFUND_APPROVED", "REFUND_REJECTED",
    }
    assert data["subject_type"] in {"ENROLLMENT", "REFUND_REQUEST"}
    assert isinstance(data.get("subject_id", ""), str) and data["subject_id"]


# ──────────────────────────────────────────────────────────
# Domain invariant: paid_amount formula (PRD §3.6)
# ──────────────────────────────────────────────────────────

def expected_paid_amount_cents(list_price_cents: int, discount_percent: int) -> int:
    """Replicate PRD §3.6: clamp discount to [0,80], compute, round half-up."""
    eff = max(0, min(80, discount_percent))
    raw = list_price_cents * (100 - eff) / 100.0
    # PRD §2.9: round half-up to nearest integer cent.
    import math
    return int(math.floor(raw + 0.5))
