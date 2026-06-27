"""Entity assertions and domain invariant checkers.

Validate response structure against the PRD contract. Every entity in this
system carries id, created_at, updated_at, and version (PRD Section 2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_location(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_level(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["sequence_order"], int) and data["sequence_order"] >= 1
    assert isinstance(data["min_age_months"], int) and data["min_age_months"] >= 0
    assert isinstance(data["max_age_months"], int)
    assert data["max_age_months"] > data["min_age_months"]
    assert isinstance(data["max_students_per_instructor"], int)
    assert data["max_students_per_instructor"] >= 1
    assert isinstance(data["monthly_tuition_cents"], int)
    assert data["monthly_tuition_cents"] >= 0


def assert_skill(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("level_id", "")), "level_id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["weight"], (int, float)) and data["weight"] > 0


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["certified_level_ids"], list)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_parent(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["account_standing"] in ["CURRENT", "PAST_DUE"]
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0


def assert_student(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("parent_id", "")), "parent_id must be a valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["age_months"], int) and data["age_months"] >= 0
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]


def assert_class_session(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["waitlist_count"], int) and data["waitlist_count"] >= 0
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED"]
    assert_session_invariants(data)


def assert_session_invariants(data: dict):
    """Seat invariant: enrolled_count never exceeds capacity (PRD Section 1)."""
    assert data["enrolled_count"] <= data["capacity"], (
        f"enrolled_count {data['enrolled_count']} must not exceed "
        f"capacity {data['capacity']}"
    )
    assert data["enrolled_count"] >= 0
    assert data["waitlist_count"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a valid UUID"
    assert is_valid_uuid(data.get("class_session_id", "")), "class_session_id must be a valid UUID"
    assert data["status"] in ["WAITLISTED", "ACTIVE", "PAUSED", "WITHDRAWN"]
    assert isinstance(data["tuition_basis_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("parent_id", "")), "parent_id must be a valid UUID"
    assert data["variant"] in ["FORWARD_LOOKING", "CHRONOLOGICAL"]
    assert isinstance(data["line_items"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "VOID"]
    assert_invoice_total_invariant(data)


def assert_invoice_total_invariant(data: dict):
    """total_cents == subtotal_cents - discount_cents (PRD Section 3.9)."""
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"], (
        f"total_cents {data['total_cents']} must equal subtotal "
        f"{data['subtotal_cents']} - discount {data['discount_cents']}"
    )


def assert_makeup_credit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a valid UUID"
    assert data["reason"] in ["SKIP", "ABSENCE", "LEVEL_TRANSFER_DISRUPTION"]
    assert data["status"] in ["ISSUED", "REDEEMED", "EXPIRED"]
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_makeup_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("makeup_credit_id", "")), "makeup_credit_id must be a valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a valid UUID"
    assert is_valid_uuid(data.get("target_class_session_id", "")), "target_class_session_id must be a valid UUID"
    assert data["status"] in ["BOOKED", "ATTENDED", "CANCELLED", "NO_SHOW"]


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be a valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a valid UUID"
    assert is_valid_uuid(data.get("assessed_level_id", "")), "assessed_level_id must be a valid UUID"
    assert isinstance(data["skill_scores"], list)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]
