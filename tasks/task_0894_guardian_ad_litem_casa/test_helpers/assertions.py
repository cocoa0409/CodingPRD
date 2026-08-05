"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_VOLUNTEER_STATUSES = ["PROSPECT", "SCREENING", "TRAINING", "ACTIVE", "INACTIVE", "RESIGNED"]
_BACKGROUND_STATUSES = ["NONE", "PENDING", "CLEARED", "FLAGGED", "EXPIRED"]
_CASE_STATUSES = ["INTAKE", "ASSIGNED", "UNASSIGNED", "CLOSED"]
_VISIT_STATUSES = ["LOGGED", "VOIDED"]
_HEARING_STATUSES = ["SCHEDULED", "HELD", "CONTINUED", "CANCELLED"]
_REPORT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "RETURNED", "FILED", "VOIDED"]
_CLAIM_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED", "PAID", "VOIDED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_audit_entry(data: dict):
    """Immutable audit entries carry id + created_at ONLY (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "audit entry must not carry a version field"
    assert "updated_at" not in data, "audit entry must not carry an updated_at field"


def assert_volunteer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in _VOLUNTEER_STATUSES, f"bad volunteer status {data['status']!r}"
    assert data["background_status"] in _BACKGROUND_STATUSES
    assert isinstance(data["max_caseload"], int)
    assert isinstance(data["active_case_count"], int) and data["active_case_count"] >= 0


def assert_supervisor(data: dict):
    _assert_common(data)
    assert data["status"] == "ACTIVE"


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in _CASE_STATUSES, f"bad case status {data['status']!r}"
    assert isinstance(data["reimbursement_budget_cents"], int)
    assert isinstance(data["reimbursement_committed_cents"], int)
    assert data["reimbursement_committed_cents"] >= 0


def assert_case_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "ENDED"], f"bad assignment status {data['status']!r}"


def assert_visit(data: dict):
    _assert_common(data)
    assert data["status"] in _VISIT_STATUSES, f"bad visit status {data['status']!r}"
    assert data["contact_type"] in ["IN_PERSON", "VIDEO", "PHONE", "COLLATERAL"]
    assert isinstance(data["duration_minutes"], (int, float))


def assert_hearing(data: dict):
    _assert_common(data)
    assert data["status"] in _HEARING_STATUSES, f"bad hearing status {data['status']!r}"
    assert data["hearing_type"] in ["STATUS", "REVIEW", "PERMANENCY", "ADJUDICATION"]


def assert_court_report(data: dict):
    _assert_common(data)
    assert data["status"] in _REPORT_STATUSES, f"bad report status {data['status']!r}"
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_background_check(data: dict):
    _assert_common(data)
    assert data["status"] in _BACKGROUND_STATUSES
    assert data["check_type"] in ["STATE_ONLY", "STATE_AND_FEDERAL"]


def assert_expense_claim(data: dict):
    _assert_common(data)
    assert data["status"] in _CLAIM_STATUSES, f"bad claim status {data['status']!r}"
    assert isinstance(data["estimated_reimbursement_cents"], int)


def assert_review_note(data: dict):
    _assert_audit_entry(data)
    assert data["decision"] in ["APPROVE", "RETURN"]


def assert_training_record(data: dict):
    _assert_audit_entry(data)
    assert isinstance(data["hours"], (int, float)) and data["hours"] > 0
