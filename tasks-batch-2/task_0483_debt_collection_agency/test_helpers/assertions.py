"""Entity assertions and domain invariant checkers (Debt Collection Agency API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every resource (PRD §2.5): id (UUID, no prefix),
    created_at / updated_at (ISO 8601), version (integer)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_creditor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["commission_basis"] in ("GROSS_OF_FEES", "NET_OF_FEES")
    assert isinstance(data["commission_rate_bps"], int)
    assert 0 <= data["commission_rate_bps"] <= 10000
    assert isinstance(data["expense_recovery_cents"], int)


def assert_consumer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["timezone_offset_minutes"], int)
    assert data["contactability"] in ("UNKNOWN", "LOCATED", "UNLOCATABLE")


def assert_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["creditor_id"])
    assert is_valid_uuid(data["consumer_id"])
    assert isinstance(data["original_principal_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["amount_collected_cents"], int)
    assert isinstance(data["amount_settled_forgiven_cents"], int)
    assert data["work_status"] in (
        "PLACED", "VALIDATION_SENT", "WORKING", "RECALLED",
        "CLOSED_PAID", "CLOSED_UNCOLLECTIBLE",
    )
    assert data["contact_status"] in (
        "PRE_VALIDATION", "CONTACTABLE", "VALIDATION_HELD", "CEASED",
    )
    assert data["sol_anchor_basis"] in ("CHARGE_OFF", "LAST_PAYMENT")
    assert isinstance(data["time_barred"], bool)
    assert isinstance(data["attempts_in_window_count"], int)
    assert isinstance(data["commission_earned_cents"], int)


def assert_communication_attempt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert data["channel"] in ("PHONE", "LETTER", "EMAIL")
    assert data["outcome"] in ("LOGGED", "CONVERSATION", "CANCELLED")
    assert isinstance(data["counts_toward_cadence"], bool)


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert data["dispute_type"] in ("VALIDATION", "ACCURACY")
    assert isinstance(data["within_validation_window"], bool)
    assert data["status"] in ("OPEN", "INVESTIGATING", "RESOLVED", "REOPENED")
    assert data.get("resolution") in (None, "VERIFIED", "DELETED")


def assert_arrangement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert data["arrangement_type"] in ("PLAN", "SETTLEMENT")
    assert data["status"] in (
        "PROPOSED", "ACCEPTED", "COUNTERED", "REJECTED", "FULFILLED", "CANCELLED",
    )
    assert isinstance(data["installment_count"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("POSTED", "REVERSED", "VOIDED")


def assert_skip_trace(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["consumer_id"])
    assert data["result"] in ("LOCATED", "NOT_FOUND")


def assert_bureau_furnishing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert data["bureau"] in ("EQUIFAX", "EXPERIAN", "TRANSUNION")
    assert isinstance(data["furnished_balance_cents"], int)
    assert data["status"] in ("REPORTED", "UPDATED", "DELETED")


def assert_bureau_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["furnishing_id"])
    assert data["status"] in ("OPEN", "RESOLVED", "REOPENED")
    assert data.get("outcome") in (None, "VERIFIED", "CORRECTED", "DELETED")


def assert_ledger_conserved(account: dict, total_money: int):
    """Ledger conservation invariant (PRD §2.9): across a payment's posting and
    later reversal/voiding with no forgiveness, balance_cents + amount_collected_cents
    is preserved."""
    actual = account["balance_cents"] + account["amount_collected_cents"]
    assert actual == total_money, (
        f"ledger conservation violated: balance_cents + amount_collected_cents "
        f"== {actual}, expected {total_money}"
    )
