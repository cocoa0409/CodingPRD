"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_system_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_account(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["kyc_status"] in ("PENDING_KYC", "VERIFIED", "RESTRICTED")
    assert data["billing_status"] in ("TRIAL", "ACTIVE", "PAST_DUE", "CLOSED")
    assert isinstance(data["cash_balance_cents"], int)
    assert data["cash_balance_cents"] >= 0, "cash_balance_cents is never negative"
    assert isinstance(data["pending_roundup_cents"], int)
    assert isinstance(data["lifetime_invested_cents"], int)
    assert isinstance(data["referral_credits_cents"], int)
    assert isinstance(data["months_billed"], int)
    assert isinstance(data["sweep_threshold_cents"], int)


def assert_subscription_plan(data: dict):
    _assert_system_fields(data)
    assert data["tier"] in ("LITE", "PERSONAL", "FAMILY")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["allows_custodial"], bool)
    assert isinstance(data["allows_ira"], bool)
    assert 0 <= data["management_fee_bps"] <= 100
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_model_portfolio(data: dict):
    _assert_system_fields(data)
    assert 1 <= data["risk_tier"] <= 5
    assert isinstance(data["target_allocation"], dict)
    assert sum(data["target_allocation"].values()) == 100
    assert data["drift_band_bps"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_found_money_offer(data: dict):
    _assert_system_fields(data)
    assert data["rebate_mode"] in ("PERCENT", "FLAT")
    assert data["status"] in ("ACTIVE", "PAUSED")
    assert is_iso8601_timestamp(data["active_from"])
    assert is_iso8601_timestamp(data["active_until"])


def assert_linked_card(data: dict):
    _assert_system_fields(data)
    assert data["roundup_multiplier"] in (1, 2, 3, 10)
    assert data["status"] in ("LINKED", "PAUSED", "UNLINKED")


def assert_roundup_accrual(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["base_roundup_cents"], int)
    assert isinstance(data["effective_amount_cents"], int)
    assert data["status"] in ("PENDING", "SWEPT", "CANCELLED")


def assert_bucket(data: dict):
    _assert_system_fields(data)
    assert data["bucket_type"] in ("TAXABLE", "UTMA", "IRA")
    assert isinstance(data["total_drift_bps"], int)
    assert isinstance(data["needs_rebalance"], bool)
    assert isinstance(data["market_value_cents"], int)
    assert data["status"] in ("OPEN", "FROZEN", "CLOSED")


def assert_order(data: dict):
    _assert_system_fields(data)
    assert data["order_kind"] in ("INVEST", "WITHDRAW")
    assert data["status"] in ("DRAFT", "SUBMITTED", "SETTLED", "REJECTED", "CANCELLED")
    assert isinstance(data["settled_amount_cents"], int)
    assert isinstance(data["realized_gain_cents"], int)
    assert isinstance(data["management_fee_cents"], int)


def assert_tax_lot(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["cost_basis_cents"], int)
    assert isinstance(data["remaining_basis_cents"], int)
    assert isinstance(data["market_value_cents"], int)
    assert data["status"] in ("OPEN", "DEPLETED")


def assert_found_money_reward(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["rebate_amount_cents"], int)
    assert is_iso8601_timestamp(data["eligible_at"])
    assert data["status"] in ("PENDING", "CONFIRMED", "REVERSED")


def assert_referral(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("ISSUED", "REDEEMED", "QUALIFIED", "EXPIRED", "REVOKED")


def assert_cash_transaction(data: dict):
    _assert_system_fields(data)
    assert data["tx_type"] in (
        "SUBSCRIPTION_FEE", "MANAGEMENT_FEE", "REFERRAL_BONUS", "FOUND_MONEY",
        "WITHDRAW_PROCEEDS", "SWEEP_DEBIT", "CONTRIBUTION_DEPOSIT",
    )
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "CONFIRMED", "VOID")
