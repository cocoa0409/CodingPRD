"""Entity assertions and domain invariant checkers for the University Registrar API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (entities that carry the full common set)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_immutable_common(data: dict):
    """id + created_at only — immutable records carry no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable record must not carry updated_at"
    assert "version" not in data, "immutable record must not carry version"


def assert_term(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["status"] in ("PLANNING", "REGISTRATION_OPEN", "IN_SESSION", "CLOSED")
    assert isinstance(data["per_credit_cost_cents"], int)


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["completed_credit_hours"], int)
    assert isinstance(data["earned_credit_hours"], int)
    assert isinstance(data["gpa"], (int, float))
    assert data["academic_standing"] in ("GOOD", "WARNING", "PROBATION")
    assert isinstance(data["tuition_owed_cents"], int)


def assert_program(data: dict):
    _assert_immutable_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["required_credit_hours"], int)
    assert isinstance(data["min_gpa"], (int, float))


def assert_course(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["credit_hours"], int)
    assert isinstance(data["is_active"], bool)


def assert_course_requirement(data: dict):
    _assert_immutable_common(data)
    assert data["requirement_type"] in ("PREREQUISITE", "COREQUISITE")


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["gap_minutes"], int)


def assert_section(data: dict):
    _assert_common(data)
    assert isinstance(data["seat_capacity"], int)
    assert isinstance(data["seats_taken"], int)
    assert isinstance(data["waitlist_count"], int)
    assert data["status"] in ("OPEN", "CLOSED", "CANCELLED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["priority_tier"], int)
    assert isinstance(data["max_credit_hours"], int)
    assert isinstance(data["enrolled_credit_hours"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["registration_status"] in (
        "REQUESTED", "ENROLLED", "WAITLISTED", "DROPPED", "WITHDRAWN",
    )
    assert data["grade_status"] in ("UNGRADED", "GRADED")


def assert_hold(data: dict):
    _assert_common(data)
    assert data["hold_type"] in ("FINANCIAL", "ADVISING")
    assert data["status"] in ("ACTIVE", "CLEARED")


def assert_swap_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "COMMITTED", "ABORTED")


def assert_refund_transaction(data: dict):
    _assert_immutable_common(data)
    assert data["refund_tier"] in ("FULL", "PARTIAL", "NONE")
    assert isinstance(data["amount_cents"], int)
    assert data["triggered_by"] in ("DROP", "WITHDRAW", "SECTION_CANCEL")
