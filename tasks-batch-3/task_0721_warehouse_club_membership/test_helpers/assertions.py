"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["PENDING_PAYMENT", "ACTIVE", "EXPIRED", "CANCELLED"]
    assert isinstance(data["reward_accrued_cents"], int)
    assert isinstance(data["reward_redeemed_cents"], int)
    assert isinstance(data["fees_paid_cents"], int)
    assert isinstance(data["household_card_count"], int)
    assert isinstance(data["version"], int)


def assert_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["tier"] in ["BASIC", "EXECUTIVE"]
    assert isinstance(data["annual_fee_cents"], int)
    # Configuration entity is not mutation-tracked.
    assert "version" not in data, "MembershipPlan must not carry a version field"


def assert_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["member_price_cents"], int)
    assert data["member_price_cents"] <= data["list_price_cents"]


def assert_transaction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "FINALIZED", "VOIDED"]
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["net_cents"] >= 0, "net_cents floored at 0"


def assert_transaction_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_instant_savings_cents"], int)
    assert isinstance(data["line_rebate_cents"], int)


def assert_household_card(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["card_kind"] in ["INCLUDED", "PAID_ADDON"]
    assert data["status"] in ["ACTIVE", "REVOKED"]


def assert_return(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["lookup_mode"] in ["RECEIPTED", "NO_RECEIPT_LOOKUP", "DENIED"]
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED"]


def assert_fee_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["kind"] in ["SIGNUP", "RENEWAL", "ADDON", "CANCEL_REFUND"]
    assert "version" not in data, "FeeEvent must not carry a version field"


def assert_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["entry_type"] in ["ACCRUAL", "REVERSAL", "REDEMPTION", "EXPIRY"]
    assert "version" not in data, "RewardLedgerEntry must not carry a version field"


def sum_ledger_amounts(entries: list) -> int:
    """Sum of all RewardLedgerEntry.amount_cents — the conserved reward quantity."""
    return sum(e["amount_cents"] for e in entries)


def sum_fee_amounts(entries: list) -> int:
    """Sum of all FeeEvent.amount_cents — the conserved net-fee quantity."""
    return sum(e["amount_cents"] for e in entries)
