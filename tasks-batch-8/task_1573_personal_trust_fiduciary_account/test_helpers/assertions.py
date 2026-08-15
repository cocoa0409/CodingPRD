"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, with_version: bool = True):
    """PRD §2.4: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive int, got {data.get('version')!r}"
        )


def assert_trust_account(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "UNDER_ACCEPTANCE_REVIEW", "ACCEPTANCE_DECLINED", "ACTIVE",
        "SUSPENDED", "TERMINATING", "TERMINATED", "CLOSED",
    ]
    for field in (
        "income_balance_cents", "principal_balance_cents",
        "reserved_income_cents", "reserved_principal_cents",
        "available_income_cents", "available_principal_cents",
        "total_market_value_cents", "pending_distribution_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer, got {data.get(field)!r}"


def assert_trust_document(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "INTERPRETED", "APPROVED", "REJECTED", "SUPERSEDED"]


def assert_beneficiary(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "DECEASED"]
    assert data["beneficiary_class"] in ["INCOME", "REMAINDER"]
    assert 1 <= data["share_bps"] <= 10000


def assert_committee_member(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_distribution_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "INFORMATION_REQUESTED", "VOTING",
        "APPROVED", "DECLINED", "DISBURSED", "WITHDRAWN", "CANCELLED",
    ]
    for field in ("income_portion_cents", "principal_portion_cents",
                  "approve_count", "decline_count", "abstain_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_committee_vote(data: dict):
    """PRD §2.4: a CommitteeVote carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["vote"] in ["APPROVE", "DECLINE", "ABSTAIN"]


def assert_ips(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED"]


def assert_holding(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "CLOSED"]
    assert data["asset_class"] in ["EQUITY", "FIXED_INCOME", "CASH_EQUIVALENT", "ALTERNATIVE"]
    assert data["market_value_cents"] == data["units"] * data["unit_price_cents"], (
        "market_value_cents must be exactly units * unit_price_cents (PRD §3.4)"
    )


def assert_compliance_review(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "REMEDIATION_PLANNED", "ESCALATED", "RESOLVED"]
    assert data["direction"] in ["OVERWEIGHT", "UNDERWEIGHT"]
    assert data["severity"] in ["STANDARD", "CRITICAL"]


def assert_ledger_entry(data: dict):
    """PRD §2.4: a LedgerEntry carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["bucket"] in ["INCOME", "PRINCIPAL"]
    assert isinstance(data["amount_cents"], int)


def assert_fee_assessment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["CALCULATED", "DISCLOSED", "DISPUTED", "POSTED", "REVERSED"]
    assert data["variant"] in ["PROVISIONAL", "FINAL"]
    for field in ("base_market_value_cents", "annual_fee_cents", "assessed_fee_cents",
                  "income_portion_cents", "principal_portion_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_annual_statement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "FINALIZED", "DELIVERED", "ACKNOWLEDGED", "DISPUTED", "SUPERSEDED"]


def assert_tax_filing(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "DATA_COLLECTION", "PREPARED", "UNDER_REVIEW", "FILED",
        "ACCEPTED", "AMENDMENT_REQUIRED",
    ]
    assert isinstance(data["amendment_number"], int)


def assert_termination_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "INITIATED", "LIABILITIES_RESERVED", "TAX_CLEARANCE_RECEIVED",
        "FINAL_ACCOUNTING_APPROVED", "DISTRIBUTED", "CLOSED",
    ]


def assert_trust_balance_invariants(trust: dict):
    """PRD §2.6: available = balance - reserved, for both buckets."""
    assert trust["available_income_cents"] == (
        trust["income_balance_cents"] - trust["reserved_income_cents"]
    ), "available_income_cents must equal income_balance_cents - reserved_income_cents"
    assert trust["available_principal_cents"] == (
        trust["principal_balance_cents"] - trust["reserved_principal_cents"]
    ), "available_principal_cents must equal principal_balance_cents - reserved_principal_cents"
