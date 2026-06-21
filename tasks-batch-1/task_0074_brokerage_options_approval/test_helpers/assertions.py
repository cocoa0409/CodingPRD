"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Account.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int), "version must be int"
    assert data["status"] in ("PENDING_KYC", "ACTIVE", "RESTRICTED", "CLOSED")
    assert data["margin_type"] in ("CASH", "REG_T", "PMA")
    assert isinstance(data["options_level"], int) and 0 <= data["options_level"] <= 4
    assert isinstance(data["cash_balance_cents"], int)
    assert isinstance(data["buying_power_cents"], int)
    assert isinstance(data["equity_cents"], int)
    assert isinstance(data["maintenance_margin_cents"], int)
    assert isinstance(data["day_trade_count"], int)
    assert isinstance(data["pdt_flagged"], bool)


def assert_options_approval(data: dict):
    assert is_valid_uuid(data.get("id", "")), "OptionsApproval.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["requested_level"], int)


def assert_margin_upgrade(data: dict):
    assert is_valid_uuid(data.get("id", "")), "MarginUpgrade.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert data["requested_margin_type"] in ("REG_T", "PMA")


def assert_position(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Position.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["instrument_type"] in ("EQUITY", "OPTION")


def assert_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Order.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in (
        "DRAFT", "ACCEPTED", "FILLED", "PARTIALLY_FILLED", "CANCELLED", "REJECTED"
    )
    assert data["instrument_type"] in ("EQUITY", "OPTION")
    assert data["side"] in ("BUY", "SELL")
    assert data["order_type"] in ("LIMIT", "STOP", "TAKE_PROFIT")


def assert_acat_transfer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "AcatTransfer.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("REQUESTED", "VALIDATED", "SETTLED", "REJECTED", "CANCELLED")
    assert data["direction"] in ("IN", "OUT")


def assert_day_trade(data: dict):
    """DayTrade is append-only: id + created_at only, no version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "DayTrade.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "DayTrade is append-only and must not carry version"
    assert "updated_at" not in data, "DayTrade is append-only and must not carry updated_at"
