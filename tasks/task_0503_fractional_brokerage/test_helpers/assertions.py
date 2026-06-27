"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape the PRD promises for that resource;
the invariant checkers express cross-field relationships the PRD says hold
after any reconcile. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------
def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Account.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["holder_email"], str) and len(data["holder_email"]) > 0
    assert data["account_type"] in ("CASH", "MARGIN"), f"bad account_type {data['account_type']}"
    assert data["trading_status"] in (
        "ACTIVE", "RESTRICTED_CLOSING_ONLY", "MARGIN_CALL", "FROZEN"
    ), f"bad trading_status {data['trading_status']}"
    assert data["options_level"] in (0, 1, 2, 3), f"bad options_level {data['options_level']}"
    assert isinstance(data["settled_cash_cents"], int)
    assert isinstance(data["buying_power_cents"], int)
    assert isinstance(data["account_equity_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_security(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Security.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["symbol"], str) and len(data["symbol"]) > 0
    assert data["instrument_type"] in ("EQUITY", "OPTION")
    assert isinstance(data["last_price_cents"], int)
    # Security is common_fields:false — no version, no updated_at (PRD §2.4).
    assert "version" not in data, "Security must not expose version"
    assert "updated_at" not in data, "Security must not expose updated_at"


def assert_deposit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Deposit.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("PENDING", "SETTLED", "REVERSED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["instant_credit_granted_cents"], int)


def assert_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Order.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["side"] in ("BUY", "SELL")
    assert data["order_type"] in ("MARKET", "LIMIT")
    assert data["order_status"] in (
        "PENDING_NEW", "ACCEPTED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED"
    )


def assert_fill(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Fill.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["gross_value_cents"], int)
    assert isinstance(data["pfof_rebate_cents"], int)
    # Fill is common_fields:false — no version, no updated_at (PRD §2.4).
    assert "version" not in data, "Fill must not expose version"
    assert "updated_at" not in data, "Fill must not expose updated_at"


def assert_settlement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Settlement.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["direction"] in ("DEBIT", "CREDIT")
    assert data["status"] in ("UNSETTLED", "SETTLED", "FAILED")


def assert_position(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Position.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["cost_basis_method"] in ("FIFO", "AVERAGE")


def assert_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Lot.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OPEN", "PARTIALLY_CLOSED", "CLOSED")


def assert_disposal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Disposal.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["term"] in ("SHORT", "LONG")
    assert isinstance(data["proceeds_cents"], int)
    assert isinstance(data["cost_basis_cents"], int)
    assert isinstance(data["realized_pl_cents"], int)


def assert_dividend(data: dict):
    assert is_valid_uuid(data.get("id", "")), "DividendEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ANNOUNCED", "PAID", "REINVESTED", "REVERSED")


def assert_options_approval(data: dict):
    assert is_valid_uuid(data.get("id", "")), "OptionsApproval.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "REVOKED")
    assert data["granted_level"] in (0, 1, 2, 3)


def assert_margin_call(data: dict):
    assert is_valid_uuid(data.get("id", "")), "MarginCall.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ISSUED", "MET", "LIQUIDATED")


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_maintenance_excess_consistent(account: dict):
    """maintenance_excess = account_equity - maintenance_requirement (PRD §3.9)."""
    assert account["maintenance_excess_cents"] == (
        account["account_equity_cents"] - account["maintenance_requirement_cents"]
    ), (
        f"maintenance_excess {account['maintenance_excess_cents']} != equity "
        f"{account['account_equity_cents']} - maintenance "
        f"{account['maintenance_requirement_cents']}"
    )
