"""Entity assertions and domain invariant checkers (Kids Allowance & Chore Card)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["family_name"], str) and len(data["family_name"]) > 0
    assert isinstance(data["funding_balance_cents"], int)
    assert data["funding_balance_cents"] >= 0, "funding wallet is never negative"
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_child_account(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["is_teen"], bool)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_jar(data: dict):
    _assert_common(data)
    assert data["jar_type"] in ("SPEND", "SAVE", "GIVE")
    assert isinstance(data["balance_cents"], int)
    assert data["balance_cents"] >= 0, "jar balance is never negative"
    assert isinstance(data["lifetime_credited_cents"], int)
    assert data["lifetime_credited_cents"] >= 0


def assert_chore(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["reward_cents"], int) and data["reward_cents"] > 0
    assert data["payout_jar_type"] in ("SPEND", "SAVE", "GIVE")
    assert isinstance(data["is_recurring"], bool)
    assert data["status"] in ("AVAILABLE", "SUBMITTED", "APPROVED", "REJECTED", "ARCHIVED")


def assert_chore_completion(data: dict):
    _assert_common(data)
    assert isinstance(data["reward_cents_snapshot"], int)
    assert data["payout_jar_type_snapshot"] in ("SPEND", "SAVE", "GIVE")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in ("PENDING_REVIEW", "NEEDS_REVISION", "PAID", "DENIED")


def assert_debit_card(data: dict):
    _assert_common(data)
    assert data["lock_state"] in ("UNLOCKED", "LOCKED")
    assert data["funding_state"] in ("FUNDED", "DRAINED")
    assert isinstance(data["held_cents"], int) and data["held_cents"] >= 0
    assert isinstance(data["available_cents"], int) and data["available_cents"] >= 0, \
        "available_cents is never negative"


def assert_card_control(data: dict):
    _assert_common(data)
    assert data["control_kind"] in ("STORE", "CATEGORY")
    assert data["rule"] in ("BLOCK", "LIMIT")
    assert isinstance(data["is_active"], bool)


def assert_transaction(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PENDING", "SETTLED", "DECLINED", "REVERSED")


def assert_allowance_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["payout_jar_type"] in ("SPEND", "SAVE", "GIVE")
    assert isinstance(data["cadence_days"], int) and data["cadence_days"] >= 1
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_allowance_run(data: dict):
    _assert_common(data)
    assert data["outcome"] in ("EXECUTED", "SKIPPED_INSUFFICIENT_FUNDS")


def assert_interest_config(data: dict):
    _assert_common(data)
    assert data["accrual_method"] in ("WHOLE_PERIOD", "DAILY_AVERAGE")
    assert data["status"] in ("ENABLED", "DISABLED")


def assert_interest_accrual(data: dict):
    _assert_common(data)
    assert isinstance(data["matched_cents"], int)
    assert is_iso8601_timestamp(data.get("accrued_at", "")), "accrued_at must be ISO 8601"


def assert_investment_account(data: dict):
    _assert_common(data)
    assert isinstance(data["cash_cents"], int) and data["cash_cents"] >= 0
    assert isinstance(data["holdings"], dict)
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_investment_order(data: dict):
    _assert_common(data)
    assert data["side"] in ("BUY", "SELL")
    assert isinstance(data["shares_milli"], int) and data["shares_milli"] > 0
    assert isinstance(data["gross_cents"], int)
    assert data["status"] in ("FILLED", "REJECTED")


def assert_spend_alert(data: dict):
    # SpendAlert is immutable: id + created_at only, NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["alert_kind"] in ("LARGE_SPEND", "LOW_BALANCE")


def assert_card_money_invariants(data: dict):
    """available_cents = linked SPEND jar balance - held_cents, never negative."""
    assert data["available_cents"] >= 0
    assert data["held_cents"] >= 0
