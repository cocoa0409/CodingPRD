"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["liquid_net_worth_cents"], int)
    assert isinstance(data["investment_experience_years"], int)
    assert data["application_status"] in (
        "SUBMITTED",
        "COMPLIANCE_REVIEW",
        "APPROVED",
        "REJECTED",
    )
    assert "reviewed_by_user_id" in data
    assert "decided_by_user_id" in data
    assert "rejection_reason" in data
    assert "account_id" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["account_status"] in ("ACTIVE", "RESTRICTED", "CLOSED")
    for f in (
        "cash_balance_cents",
        "equity_realtime_cents",
        "equity_official_cents",
        "reg_req_official_cents",
        "house_req_official_cents",
        "reg_req_realtime_cents",
        "house_req_realtime_cents",
        "buying_power_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert isinstance(data["pdt_flag"], bool)
    assert "pdt_flagged_at" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_security_profile(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["symbol"], str) and data["symbol"]
    assert isinstance(data["marginable"], bool)
    assert isinstance(data["house_maint_long_bps"], int)
    assert isinstance(data["house_maint_short_bps"], int)
    assert isinstance(data["liquidity_tier"], int)
    assert isinstance(data["concentration_threshold_bps"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_position(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    for f in (
        "quantity",
        "avg_cost_cents",
        "mv_realtime_cents",
        "mv_official_cents",
        "reserved_qty",
        "today_bought_qty",
        "today_sold_qty",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert "last_trade_date" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_margin_call(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["call_type"] in (
        "FED_REG_T",
        "MAINTENANCE",
        "HOUSE",
        "DAY_TRADE_MIN_EQUITY",
    )
    assert data["call_status"] in (
        "OPEN",
        "DISPUTED",
        "EXPIRED",
        "LIQUIDATION_IN_PROGRESS",
        "CURED",
        "WAIVED",
    )
    assert isinstance(data["call_amount_cents"], int)
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert "resolved_at" in data
    assert "cure_method" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_liquidation_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("call_id", ""))
    assert is_valid_uuid(data.get("position_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["filled_quantity"], int) and data["filled_quantity"] >= 0
    assert isinstance(data["proceeds_cents"], int)
    assert data["order_status"] in (
        "PENDING",
        "PARTIALLY_FILLED",
        "EXECUTED",
        "CANCELLED",
    )
    assert isinstance(data["created_by_user_id"], str)
    assert "last_filled_by_user_id" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_cash_movement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["movement_type"] in (
        "DEPOSIT",
        "WITHDRAWAL",
        "JOURNAL_CREDIT",
        "JOURNAL_DEBIT",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["resulting_cash_balance_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_rate_tier(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["tier_level"], int)
    assert isinstance(data["min_balance_cents"], int)
    assert isinstance(data["annual_rate_bps"], int)
    assert isinstance(data["effective_from"], str)
    assert "effective_to" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_dispute(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("call_id", ""))
    assert isinstance(data["reason"], str)
    assert data["dispute_status"] in (
        "OPEN",
        "UNDER_REVIEW",
        "UPHELD",
        "OVERTURNED",
        "CLOSED",
    )
    assert "reviewed_by_user_id" in data
    assert "decided_by_user_id" in data
    assert "decision" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def _assert_ledger_fields(data: dict):
    """Ledger-style records carry only id and created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "ledger record must not carry updated_at"
    assert "version" not in data, "ledger record must not carry version"


def assert_trade_fill(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    assert data["side"] in ("BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["fill_date"], str)
    assert isinstance(data["is_day_trade"], bool)


def assert_day_trade_event(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    assert isinstance(data["event_date"], str)


def assert_price_mark(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("security_id", ""))
    assert data["mark_type"] in ("REALTIME", "OFFICIAL_CLOSE")
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert is_iso8601_timestamp(data.get("marked_at", ""))


def assert_interest_ledger_entry(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["entry_type"] in ("DAILY_ACCRUAL", "MONTHLY_POST")
    assert isinstance(data["accrual_date"], str)
    assert isinstance(data["debit_balance_snapshot_cents"], int)
    assert isinstance(data["rate_bps_applied"], int)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["posted"], bool)
