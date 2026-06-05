"""Entity assertions and domain invariant checkers.

Use the framework's generic structural validators internally. Every entity here
exposes the full id / created_at / updated_at / version quartet (PRD §2.4).
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policyholder_name"], str) and data["policyholder_name"]
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED")
    assert data["comparative_fault_rule"] in ("PURE", "MODIFIED_50", "MODIFIED_51")
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])


def assert_coverage(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert data["coverage_type"] in ("COLLISION", "COMPREHENSIVE", "RENTAL")
    assert isinstance(data["limit_cents"], int)


def assert_adjuster(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["license_tier"] in ("STANDARD", "SENIOR")
    assert isinstance(data["active"], bool)


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert data["status"] in (
        "FNOL_SUBMITTED", "COVERAGE_VERIFIED", "COVERAGE_DENIED", "UNDER_REVIEW",
        "REPAIR_APPROVED", "TOTAL_LOSS", "SETTLED", "CLOSED", "REOPENED",
    )
    assert data["loss_type"] in ("COLLISION", "COMPREHENSIVE")
    assert isinstance(data["vehicle_acv_cents"], int)
    assert 0 <= data["insured_fault_pct"] <= 100
    assert data["disposition"] in (None, "REPAIR", "TOTAL_LOSS")
    assert isinstance(data["settlement_cents"], int)
    assert isinstance(data["total_disbursed_cents"], int)


def assert_claim_party(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["party_role"] in ("INSURED", "THIRD_PARTY")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert 0 <= data["fault_pct"] <= 100


def assert_coverage_verification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["outcome"] in ("VERIFIED", "DENIED")
    assert data["matched_coverage_type"] in (None, "COLLISION", "COMPREHENSIVE")
    assert data["denial_reason"] in (
        None, "POLICY_INACTIVE", "OUTSIDE_COVERAGE_WINDOW", "NO_MATCHING_COVERAGE",
    )


def assert_repair_estimate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["authored_by_adjuster_id"])
    assert isinstance(data["repair_total_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "SUPERSEDED")


def assert_total_loss_evaluation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["evaluated_by_adjuster_id"])
    assert isinstance(data["acv_cents"], int)
    assert isinstance(data["repair_total_cents"], int)
    assert isinstance(data["total_loss_ratio"], (int, float))
    assert isinstance(data["is_total_loss"], bool)
    assert isinstance(data["salvage_retained_by_insurer"], bool)


def assert_rental_reimbursement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["reimbursable_days"], int)
    assert isinstance(data["reimbursement_cents"], int)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_subrogation_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["target_party_id"])
    assert isinstance(data["demand_cents"], int)
    assert isinstance(data["recoverable_cents"], int)
    assert data["status"] in (
        "OPEN", "DEMAND_SENT", "NEGOTIATING", "RESOLVED", "CLOSED_NO_RECOVERY",
    )


def assert_disbursement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["disbursement_type"] in ("SETTLEMENT", "RENTAL", "SUBROGATION_RECOVERY")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("APPROVED", "VOIDED")
