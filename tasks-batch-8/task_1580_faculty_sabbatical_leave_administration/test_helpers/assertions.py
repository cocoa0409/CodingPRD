"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_department(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["replacement_pool"] > 0
    assert data["posture"] in ("OPEN", "CONSTRAINED", "FROZEN")
    for f in ("reserved_amount", "spent_amount", "available_amount"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_department_budget_invariant(data: dict):
    """PRD: reserved + spent + available always sums back to replacement_pool."""
    total = data["reserved_amount"] + data["spent_amount"] + data["available_amount"]
    assert total == pytest.approx(data["replacement_pool"], abs=0.005), (
        f"budget invariant violated: {data['reserved_amount']} + {data['spent_amount']} "
        f"+ {data['available_amount']} != {data['replacement_pool']}"
    )


def assert_faculty_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert data["academic_rank"] in (
        "ASSISTANT_PROFESSOR",
        "ASSOCIATE_PROFESSOR",
        "FULL_PROFESSOR",
    )
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "SEPARATED")
    assert isinstance(data["credit_balance"], int)
    assert isinstance(data["lifetime_service_months"], int)


def assert_leave_cycle(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "ALLOCATED", "FINALIZED")
    assert isinstance(data["award_quota"], int) and data["award_quota"] >= 1
    assert isinstance(data["awarded_count"], int)


def assert_leave_application(data: dict):
    _assert_common_fields(data)
    assert data["leave_type"] in ("SABBATICAL", "MEDICAL", "PERSONAL", "PROFESSIONAL")
    assert data["status"] in (
        "DRAFT",
        "UNDER_REVIEW",
        "REVISION_REQUESTED",
        "AWARDED",
        "NOT_AWARDED",
        "APPROVED",
        "DENIED",
        "WITHDRAWN",
        "RESCINDED",
    )
    assert data["funding_status"] in (
        "NONE",
        "COVERAGE_SUBMITTED",
        "COVERAGE_APPROVED",
        "COVERAGE_CONFIRMED",
        "COVERAGE_SETTLED",
        "COVERAGE_RELEASED",
    )
    assert isinstance(data["submitted_review_count"], int)
    assert isinstance(data["quorum_met"], bool)


def assert_committee_review(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED")
    assert isinstance(data["weighted_total"], (int, float))


def assert_coverage_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "REVISION_REQUESTED",
        "SUPERSEDED",
        "CONFIRMED",
        "SETTLED",
        "RELEASED",
    )
    assert 1 <= data["courses_to_cover"] <= 40
    assert isinstance(data["provisional_cost"], (int, float))


def assert_leave_grant(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "CURTAILED", "CANCELLED")
    assert data["leave_type"] in ("SABBATICAL", "MEDICAL", "PERSONAL", "PROFESSIONAL")


def assert_external_fellowship(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("REPORTED", "VERIFIED", "APPLIED", "DECLINED")
    assert data["amount"] > 0


def assert_service_obligation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("IN_PROGRESS", "FULFILLED", "BREACHED")
    assert isinstance(data["required_months"], int) and data["required_months"] >= 1
    assert isinstance(data["fulfilled_months"], int) and data["fulfilled_months"] >= 0


def assert_repayment_obligation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "DEFAULTED", "SETTLED", "WAIVED")
    assert isinstance(data["amount_owed"], (int, float))
    assert isinstance(data["amount_outstanding"], (int, float))


def assert_repayment_payment(data: dict):
    """Payments are append-only: only id + created_at among common fields."""
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "RepaymentPayment must not carry updated_at"
    assert "version" not in data, "RepaymentPayment must not carry version"
    assert data["amount"] > 0
    assert isinstance(data["resulting_outstanding"], (int, float))


def assert_accomplishment_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DUE", "OVERDUE", "SUBMITTED", "ACCEPTED", "REVISION_REQUIRED")
    assert isinstance(data["submitted_late"], bool)


def assert_accrual_ledger_entry(data: dict):
    """Ledger entries are append-only: only id + created_at among common fields."""
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "AccrualLedgerEntry must not carry updated_at"
    assert "version" not in data, "AccrualLedgerEntry must not carry version"
    assert data["entry_type"] in ("EARN", "CONSUME", "RESTORE", "ADJUST")
    assert isinstance(data["credits_delta"], int)
