"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_data_field(data: dict):
    _assert_common(data)
    assert data["field_key"] in (
        "assignment.position_id",
        "assignment.salary_cents",
        "assignment.pay_grade",
        "assignment.location_code",
        "position.parent_position_id",
        "position.title",
        "position.department",
    )
    assert isinstance(data["display_name"], str)
    assert data["sensitivity"] in ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
    assert data["history_policy"] in ("CORRECTABLE", "APPEND_ONLY")
    assert isinstance(data["downstream_channels"], list)
    assert set(data["downstream_channels"]) <= {"PAYROLL", "BENEFITS", "IDENTITY"}
    assert isinstance(data["owner_team"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "DEPRECATED")


def assert_position(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["department"], str)
    assert isinstance(data["headcount_budget"], int) and data["headcount_budget"] >= 0
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_worker(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["worker_number"], str)
    assert isinstance(data["hire_date"], str)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert "termination_date" in data


def assert_position_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["worker_id"], str)
    assert isinstance(data["position_id"], str)
    assert "change_request_id" in data
    assert isinstance(data["salary_cents"], int)
    assert isinstance(data["effective_start_date"], str)
    assert "effective_end_date" in data
    assert data["row_status"] in ("FUTURE", "ACTIVE", "HISTORY", "VOIDED")


def assert_change_request(data: dict):
    _assert_common(data)
    assert data["target_type"] in ("WORKER_FIELD", "POSITION_FIELD", "POSITION_HIERARCHY")
    assert isinstance(data["target_field_id"], str)
    assert isinstance(data["new_value"], str)
    assert data["status"] in (
        "PENDING_APPROVAL", "PARTIALLY_APPROVED", "APPROVED",
        "REJECTED", "SUPERSEDED", "APPLIED", "VOIDED",
    )
    assert isinstance(data["created_by"], str)


def assert_mass_change_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["status"] in (
        "DRAFT", "VALIDATED", "VALIDATION_FAILED", "SCHEDULED",
        "COMPLETED", "COMPLETED_WITH_ERRORS", "ROLLED_BACK",
    )
    assert isinstance(data["total_lines"], int)
    assert isinstance(data["applied_lines"], int)
    assert isinstance(data["failed_lines"], int)
    assert isinstance(data["total_delta_cents"], int)


def assert_batch_line(data: dict):
    _assert_common(data)
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["line_index"], int) and data["line_index"] >= 0
    assert isinstance(data["target_worker_id"], str)
    assert isinstance(data["target_field_id"], str)
    assert isinstance(data["new_value"], str)
    assert data["status"] in ("PENDING", "VALIDATED", "FAILED", "APPLIED", "ROLLED_BACK")
    assert "error_id" in data
    assert "resolved_delta_cents" in data


def assert_integration_event(data: dict):
    _assert_common(data)
    assert data["event_type"] in ("CHANGE_APPLIED", "CORRECTION_PROPAGATED", "REVERSAL")
    assert data["channel"] in ("PAYROLL", "BENEFITS", "IDENTITY")
    assert data["status"] in (
        "QUEUED", "DISPATCHED", "ACKNOWLEDGED", "FAILED",
        "DEAD_LETTERED", "RESOLVED", "CANCELLED",
    )
    assert isinstance(data["retry_count"], int)


def assert_data_quality_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["target_field_id"], str)
    assert data["rule_type"] in ("RANGE", "REQUIRED", "REGEX")
    assert data["severity"] in ("WARNING", "CRITICAL")
    assert data["status"] in ("ACTIVE", "DISABLED")


def assert_exception_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "WAIVED")
    assert isinstance(data["priority_score"], int)
    assert "waiver_expiry_date" in data


def assert_security_role_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["user_id"], str)
    assert data["role_code"] in (
        "HRIS_ANALYST", "DATA_STEWARD", "CHANGE_APPROVER",
        "INTEGRATION_OPERATOR", "SECURITY_ADMIN",
    )
    assert data["status"] in ("REQUESTED", "APPROVED", "PROVISIONED", "REVOKED", "EXPIRED")


def assert_audit_entry(data: dict):
    """Append-only log: id + created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "audit entries must not expose version"
    assert "updated_at" not in data, "audit entries must not expose updated_at"
    assert data["action"] in (
        "APPLY", "CORRECT", "VOID", "BATCH_APPLY", "BATCH_VOID",
        "GRANT_APPROVE", "GRANT_REVOKE",
    )


def assert_error_envelope(body: dict):
    """Fixed error envelope: response_type 'error', data.error_id + non-empty message."""
    assert body.get("response_type") == "error", f"expected error envelope, got {body}"
    assert isinstance(body.get("data"), dict)
    assert isinstance(body["data"].get("error_id"), str) and body["data"]["error_id"]
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"]
