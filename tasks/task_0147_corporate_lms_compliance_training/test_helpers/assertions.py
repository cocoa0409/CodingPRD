"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) checks identity/timestamp shape and the field set the
PRD declares for that resource. Append-only records (QuizAttempt, EscalationEvent)
are asserted to carry only id + created_at (no updated_at, no version).
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# --- Shared shape helpers --------------------------------------------------
def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for full top-level resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at — never version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry 'version'"
    assert "updated_at" not in data, "append-only record must not carry 'updated_at'"


# --- Per-entity assertions -------------------------------------------------
def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["department"] in ("ENGINEERING", "SALES", "FINANCE", "HR", "OPERATIONS")
    assert data["job_role"] in ("IC", "MANAGER", "DIRECTOR")
    assert isinstance(data["total_ceu_earned"], (int, float))
    assert isinstance(data["compliant_required_count"], int)
    assert isinstance(data["compliance_score"], (int, float))
    assert data["status"] == "ACTIVE"


def assert_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["content_type"] in ("SCORM", "XAPI")
    assert isinstance(data["passing_score"], int) and 0 <= data["passing_score"] <= 100
    assert isinstance(data["max_attempts"], int) and data["max_attempts"] > 0
    assert data["grading_policy"] in ("HIGHEST_SCORE", "LATEST_ATTEMPT")
    assert data["ceu_policy"] in ("STANDARD", "SCORE_WEIGHTED")
    assert isinstance(data["is_recurring"], bool)
    assert data["status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")


def assert_learning_path(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["enforce_sequence"], bool)
    assert data["status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")


def assert_path_step(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("learning_path_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["is_mandatory"], bool)
    assert isinstance(data["weight"], int)


def assert_assignment_rule(data: dict):
    _assert_common_fields(data)
    assert data["target_department"] in ("ENGINEERING", "SALES", "FINANCE", "HR", "OPERATIONS", "ANY")
    assert data["target_job_role"] in ("IC", "MANAGER", "DIRECTOR", "ANY")
    # exactly one target is set
    has_course = data.get("course_id") is not None
    has_path = data.get("learning_path_id") is not None
    assert has_course != has_path, "exactly one of course_id / learning_path_id must be set"
    assert isinstance(data["due_in_days"], int) and data["due_in_days"] >= 0
    assert data["status"] == "ACTIVE"


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["is_required"], bool)
    assert is_iso8601_timestamp(data.get("due_date", "")), "due_date must be ISO 8601"
    assert isinstance(data["attempts_used"], int) and data["attempts_used"] >= 0
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["escalation_tier"], int) and 0 <= data["escalation_tier"] <= 3
    assert data["status"] in (
        "NOT_STARTED", "IN_PROGRESS", "COMPLETED", "FAILED", "EXPIRED", "WAIVED"
    )


def assert_path_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("learning_path_id", ""))
    assert is_iso8601_timestamp(data.get("due_date", "")), "due_date must be ISO 8601"
    assert isinstance(data["progress_pct"], (int, float)) and 0 <= data["progress_pct"] <= 100
    assert data["status"] in ("NOT_STARTED", "IN_PROGRESS", "COMPLETED", "FAILED")


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["ceu_credited"], (int, float))
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_tracking_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["content_type"] in ("SCORM", "XAPI")
    assert is_iso8601_timestamp(data.get("started_at", "")), "started_at must be ISO 8601"
    assert data["status"] in ("INITIALIZED", "RUNNING", "TERMINATED")


def assert_quiz_attempt(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert isinstance(data["passed"], bool)


def assert_escalation_event(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("employee_id", ""))
    assert isinstance(data["tier"], int) and 1 <= data["tier"] <= 3
    assert isinstance(data["days_overdue"], int)
    assert isinstance(data["acknowledged"], bool)


# --- Domain invariant checkers --------------------------------------------
def assert_two_decimal_places(value: float):
    """A money/percentage value carried to exactly two decimal places."""
    assert isinstance(value, (int, float)), f"expected numeric, got {value!r}"
    rounded = round(float(value), 2)
    assert abs(float(value) - rounded) < 1e-9, f"{value} is not at 2-decimal precision"
