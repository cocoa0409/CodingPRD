"""Entity assertions and domain invariant checkers.

These assert the structural shape the PRD's common-resource rules guarantee
(PRD section 2.4) plus the entity-specific field presence. Behavioral rules
(transitions, amounts) live in the test files themselves.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["naic_code"], str) and data["naic_code"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_tpa(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_id"], str) and data["carrier_id"]
    assert data["line_of_business"] in (
        "COMMERCIAL_AUTO", "GENERAL_LIABILITY", "PROPERTY",
        "WORKERS_COMPENSATION", "PROFESSIONAL_LIABILITY")
    assert isinstance(data["states_covered"], list)
    assert isinstance(data["aggregate_limit_cents"], int)
    assert isinstance(data["consumed_aggregate_cents"], int)
    assert isinstance(data["trust_balance_cents"], int)
    assert data["status"] in (
        "PROPOSED", "ACTIVE", "SUSPENDED", "RUN_OFF", "TERMINATED", "DECLINED")


def assert_guideline(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "INACTIVE")
    assert isinstance(data["max_policy_premium_cents"], int)
    assert isinstance(data["max_policy_limit_cents"], int)


def assert_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "SUPERSEDED", "RELEASED")
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["consumed_cents"], int)


def assert_filing(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "DISAPPROVED", "EFFECTIVE",
        "SUPERSEDED", "WITHDRAWN")
    assert isinstance(data["base_rates"], dict)
    assert isinstance(data["policy_fee_cents"], int)
    assert isinstance(data["version_seq"], int)


def assert_policy(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "QUOTED", "BOUND", "ISSUED", "PENDING_CANCELLATION", "CANCELLED",
        "EXPIRED", "WITHDRAWN")
    assert data["audit_status"] in ("NOT_AUDITED", "AUDITED")
    assert isinstance(data["gross_premium_cents"], int)
    assert isinstance(data["mga_commission_cents"], int)
    assert isinstance(data["collected_cents"], int)
    assert isinstance(data["earned_premium_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REPORTED", "UNDER_REVIEW", "REFERRED", "APPROVED", "DENIED", "PAID",
        "REOPENED", "CLOSED")
    assert data["claim_type"] in (
        "PROPERTY_DAMAGE", "BODILY_INJURY", "LIABILITY", "OTHER")
    assert isinstance(data["amount_claimed_cents"], int)
    assert isinstance(data["case_reserve_cents"], int)
    assert isinstance(data["reopened_count"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED")
    assert data["claim_type"] in (
        "PROPERTY_DAMAGE", "BODILY_INJURY", "LIABILITY", "OTHER")
    assert isinstance(data["authority_limit_cents"], int)


def assert_ledger_entry(data: dict):
    # Append-only record: id + created_at only, NO updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, \
        "ledger entries are append-only: updated_at must be absent"
    assert "version" not in data, \
        "ledger entries are append-only: version must be absent"
    assert data["entry_type"] in (
        "COLLECTION", "REFUND", "CLAIM_PAYMENT", "CARRIER_REMITTANCE")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["running_balance_cents"], int)


def assert_bordereau(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "CANCELLED")
    assert data["bordereau_type"] in ("PREMIUM", "CLAIMS")
    assert isinstance(data["rows"], list)
    assert isinstance(data["computed_totals"], dict)
    assert isinstance(data["row_count"], int)
    assert isinstance(data["overdue"], bool)


def assert_audit(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "FINDINGS_ISSUED", "REMEDIATION", "CLOSED",
        "ESCALATED")
    assert data["scope"] in ("UNDERWRITING", "CLAIMS", "TRUST_ACCOUNTING", "FULL")
    assert isinstance(data["findings"], list)


def assert_loss_evaluation(data: dict):
    _assert_common(data)
    assert data["outcome"] in (
        "INSUFFICIENT_DATA", "OK", "CORRECTIVE_ACTION", "TERMINATION_REVIEW")
    assert isinstance(data["earned_premium_cents"], int)
    assert isinstance(data["paid_losses_cents"], int)
    assert isinstance(data["case_reserves_cents"], int)


def assert_trust_invariant(program: dict, ledger_entries: list):
    """trust_balance_cents is exactly the sum of amount_cents over entries
    (PRD section 2.8) and matches the last entry's running balance."""
    total = sum(e["amount_cents"] for e in ledger_entries)
    assert program["trust_balance_cents"] == total, (
        f"trust_balance_cents {program['trust_balance_cents']} diverges from "
        f"ledger sum {total}")
    if ledger_entries:
        assert ledger_entries[-1]["running_balance_cents"] == total
