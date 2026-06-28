"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) verifies the system-managed shape of a returned
resource using the framework's generic validators. Append-only entities
(BillingEntry, EssayVersion) are checked to carry only id + created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for full-field entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def _assert_append_only_fields(data: dict):
    """id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_counselor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["weekly_review_capacity"], int) and data["weekly_review_capacity"] >= 0


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["counselor_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["intake_status"] in [
        "PROSPECT", "ONBOARDED", "ACTIVE", "GRADUATED", "WITHDRAWN"
    ]
    assert isinstance(data["list_locked"], bool)
    assert 0.0 <= data["gpa"] <= 4.0
    assert data["sat_total"] == 0 or 400 <= data["sat_total"] <= 1600


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["counselor_id"], str)
    assert data["billing_model"] in ["PACKAGE", "HOURLY"]
    assert data["status"] in ["DRAFT", "ACTIVE", "CLOSED", "VOID"]


def assert_billing_entry(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "BillingEntry is append-only; must not carry updated_at"
    assert "version" not in data, "BillingEntry is append-only; must not carry version"
    assert data["entry_type"] in ["CHARGE", "CREDIT"]
    assert data["source_kind"] in ["TASK", "APPOINTMENT", "ESSAY", "MANUAL"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_school_list_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert data["round"] in ["ED", "EA", "RD", "NONE"]
    assert data["classification"] in ["REACH", "TARGET", "SAFETY"]
    assert data["status"] in ["CANDIDATE", "SELECTED", "DROPPED"]
    assert 0.0 <= data["admit_probability"] <= 1.0


def assert_application(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert data["round"] in ["ED", "EA", "RD"]
    assert data["prep_status"] in ["NOT_STARTED", "IN_PROGRESS", "READY", "SUBMITTED"]
    assert data["decision_status"] in [
        "PENDING", "ADMITTED", "DENIED", "WAITLISTED", "DEFERRED", "APPEALING"
    ]
    assert isinstance(data["open_task_count"], int) and data["open_task_count"] >= 0


def assert_application_task(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["application_id"], str)
    assert data["task_type"] in ["ESSAY", "RECOMMENDATION", "FORM", "FEE", "TRANSCRIPT"]
    assert data["status"] in ["OPEN", "IN_PROGRESS", "BLOCKED", "DONE", "WAIVED"]
    assert isinstance(data["blocks_submission"], bool)


def assert_essay(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert data["status"] in [
        "DRAFTING", "IN_REVIEW", "REVISION_REQUESTED", "APPROVED", "ABANDONED"
    ]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["latest_version_no"], int) and data["latest_version_no"] >= 0


def assert_essay_version(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "EssayVersion is append-only; must not carry updated_at"
    assert "version" not in data, "EssayVersion is append-only; must not carry version"
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert data["submitted_by_role"] in ["Student", "Counselor"]


def assert_recommendation(data: dict):
    _assert_common_fields(data)
    assert data["rec_type"] in ["TEACHER", "COUNSELOR", "OTHER"]
    assert data["status"] in ["REQUESTED", "ACCEPTED", "SUBMITTED", "DECLINED"]


def assert_activity(data: dict):
    _assert_common_fields(data)
    assert data["category"] in [
        "ACADEMIC", "ATHLETIC", "ARTS", "SERVICE", "WORK", "LEADERSHIP"
    ]
    assert 1 <= data["tier"] <= 4


def assert_scholarship(data: dict):
    _assert_common_fields(data)
    assert data["award_type"] in ["MERIT", "NEED", "EXTERNAL"]
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED"]
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] > 0


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert data["meeting_type"] in ["STRATEGY", "ESSAY_REVIEW", "CHECK_IN"]
    assert data["status"] in ["BOOKED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["billed_minutes"], int) and data["billed_minutes"] >= 0


def assert_ledger_consistency(data: dict):
    """Invariant: retainer_balance_cents == credited_cents - charged_cents."""
    assert data["retainer_balance_cents"] == data["credited_cents"] - data["charged_cents"], (
        f"retainer_balance_cents must equal credited_cents - charged_cents; "
        f"got {data['retainer_balance_cents']} vs "
        f"{data['credited_cents']} - {data['charged_cents']}"
    )
