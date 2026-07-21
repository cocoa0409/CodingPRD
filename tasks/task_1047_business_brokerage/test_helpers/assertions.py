"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_fields(data: dict, expect_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    if expect_version:
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_broker(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["firm_name"], str) and len(data["firm_name"]) > 0
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert isinstance(data["accrued_commission_cents"], int)
    assert data["accrued_commission_cents"] >= 0


def assert_buyer(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["proof_of_funds_cents"], int)
    assert isinstance(data["committed_capital_cents"], int)
    assert isinstance(data["escrowed_cents"], int)
    assert isinstance(data["available_capital_cents"], int)
    assert_buyer_capital_invariants(data)


def assert_buyer_capital_invariants(data: dict):
    """PRD Section 2.8: available = proof - committed - escrowed; encumbrances non-negative."""
    assert data["committed_capital_cents"] >= 0, "committed_capital_cents must be non-negative"
    assert data["escrowed_cents"] >= 0, "escrowed_cents must be non-negative"
    expected = (
        data["proof_of_funds_cents"]
        - data["committed_capital_cents"]
        - data["escrowed_cents"]
    )
    assert data["available_capital_cents"] == expected, (
        f"available_capital_cents must equal proof - committed - escrowed; "
        f"expected {expected}, got {data['available_capital_cents']}"
    )


def assert_listing(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in [
        "DRAFT", "ACTIVE", "UNDER_LOI", "IN_ESCROW", "SOLD", "WITHDRAWN",
    ]
    assert is_valid_uuid(data.get("broker_id", "")), "listing broker_id must be a UUID"
    assert is_valid_uuid(data.get("seller_id", "")), "listing seller_id must be a UUID"


def assert_cim(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ["DRAFT", "PUBLISHED"]
    assert data["valuation_method"] in ["SDE_MULTIPLE", "ASSET_BASED"]


def assert_deal(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in [
        "PROSPECT", "QUALIFIED", "UNDER_LOI", "DUE_DILIGENCE",
        "FINANCING", "IN_ESCROW", "CLOSED", "WITHDRAWN",
    ]


def assert_loi(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN",
    ]
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1


def assert_loan(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in [
        "SUBMITTED", "APPROVED", "CONDITIONALLY_APPROVED", "DECLINED",
    ]


def assert_escrow(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ["OPENED", "FUNDED", "CLOSED", "CANCELLED"]
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
