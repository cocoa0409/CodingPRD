"""Entity assertions and domain invariant checkers (PRD-exact field names)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _approx(value, expected, tol=1e-6):
    return abs(float(value) - float(expected)) <= tol


# --- Account (PRD §3.1, common_fields: true) ----------------------------------
def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "account id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["residence_country"], str)
    assert data["kyc_tier"] in ["TIER_0", "TIER_1", "TIER_2", "TIER_3"]
    assert data["kyc_status"] in ["UNVERIFIED", "PENDING", "APPROVED", "REJECTED"]
    assert data["account_status"] in ["ACTIVE", "FROZEN"]
    assert data["cost_basis_method"] in ["FIFO", "HIFO"]
    assert isinstance(data["version"], int) and data["version"] >= 1


# --- AssetConfig (PRD §3.3, common_fields: false — no version/updated_at) ------
def assert_asset_config(data: dict):
    assert is_valid_uuid(data.get("id", "")), "asset id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert isinstance(data["symbol"], str) and len(data["symbol"]) > 0
    assert isinstance(data["decimals"], int)
    assert isinstance(data["required_confirmations"], int)
    assert isinstance(data["is_fiat"], bool)
    # PRD §2.4: configuration/append-only entities carry no version, no updated_at.
    assert "version" not in data, "AssetConfig must not carry a version field"
    assert "updated_at" not in data, "AssetConfig must not carry an updated_at field"


# --- Balance (PRD §2.6, common_fields: true) ----------------------------------
def assert_balance(data: dict):
    assert is_valid_uuid(data.get("id", "")), "balance id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["asset"], str)
    for f in ("total_amount", "reserved_amount", "held_amount", "available_amount"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_balance_partition_reconciles(data: dict):
    """PRD §2.6: available_amount == total_amount - reserved_amount - held_amount;
    total_amount == available + reserved + held."""
    expected_available = (
        data["total_amount"] - data["reserved_amount"] - data["held_amount"]
    )
    assert _approx(data["available_amount"], expected_available), (
        f"available_amount {data['available_amount']} != total - reserved - held "
        f"{expected_available}"
    )


# --- Deposit (PRD §3.4, common_fields: true) ----------------------------------
def assert_deposit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "deposit id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["asset"], str)
    assert isinstance(data["amount"], (int, float))
    assert isinstance(data["confirmations"], int)
    assert data["status"] in ["DETECTED", "CONFIRMING", "CREDITED", "ORPHANED"]


# --- WithdrawalAddress (PRD §3.5, common_fields: true) ------------------------
def assert_withdrawal_address(data: dict):
    assert is_valid_uuid(data.get("id", "")), "address id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["asset"], str)
    assert isinstance(data["chain_address"], str)
    assert data["status"] in ["PENDING_HOLD", "ACTIVE", "REMOVED"]


# --- Withdrawal (PRD §3.6, common_fields: true) ------------------------------
def assert_withdrawal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "withdrawal id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["withdrawal_address_id"], str)
    assert isinstance(data["amount"], (int, float))
    assert isinstance(data["notional_usd"], (int, float))
    assert isinstance(data["requires_travel_rule"], bool)
    assert data["status"] in [
        "SUBMITTED", "SCREENING", "TRAVEL_RULE_HOLD", "APPROVED",
        "BROADCAST", "COMPLETED", "REJECTED",
    ]


# --- TravelRuleRecord (PRD §3.6, common_fields: true) ------------------------
def assert_travel_rule_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "record id must be a valid UUID"
    assert isinstance(data["withdrawal_id"], str)
    assert data["status"] == "FILED"


# --- Order (PRD §3.8, common_fields: true) -----------------------------------
def assert_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "order id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["base_asset"], str)
    assert isinstance(data["quote_asset"], str)
    assert data["side"] in ["BUY", "SELL"]
    assert data["order_type"] in ["MARKET", "LIMIT"]
    assert isinstance(data["quantity"], (int, float))
    assert isinstance(data["filled_quantity"], (int, float))
    assert data["lifecycle_status"] in [
        "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED",
    ]
    assert data["time_in_force"] in ["GTC", "IOC"]


# --- Trade (PRD §3.8, common_fields: false — no version/updated_at) -----------
def assert_trade(data: dict):
    assert is_valid_uuid(data.get("id", "")), "trade id must be a valid UUID"
    assert isinstance(data["maker_order_id"], str)
    assert isinstance(data["taker_order_id"], str)
    assert isinstance(data["price"], (int, float))
    assert isinstance(data["quantity"], (int, float))
    assert isinstance(data["notional_usd"], (int, float))
    assert isinstance(data["maker_fee"], (int, float))
    assert isinstance(data["taker_fee"], (int, float))
    # PRD §2.4: append-only execution record — no version, no updated_at.
    assert "version" not in data, "Trade must not carry a version field"
    assert "updated_at" not in data, "Trade must not carry an updated_at field"


# --- CostBasisLot (PRD §3.10, common_fields: true) ---------------------------
def assert_cost_basis_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "lot id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["asset"], str)
    assert data["origin_type"] in ["DEPOSIT", "TRADE_BUY", "STAKING_REWARD"]
    assert isinstance(data["original_quantity"], (int, float))
    assert isinstance(data["remaining_quantity"], (int, float))
    assert isinstance(data["unit_cost_usd"], (int, float))
    assert data["status"] in ["OPEN", "DEPLETED"]


# --- StakingPosition (PRD §3.11, common_fields: true) ------------------------
def assert_staking_position(data: dict):
    assert is_valid_uuid(data.get("id", "")), "position id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["asset"], str)
    assert isinstance(data["principal_amount"], (int, float))
    assert data["status"] in ["ACTIVE", "UNBONDING", "CLOSED"]


# --- Helpers to locate rows in list responses ---------------------------------
def find_lot_by_unit_cost(lots: list, unit_cost_usd) -> dict:
    """Return the single CostBasisLot whose unit_cost_usd matches."""
    matches = [l for l in lots if _approx(l["unit_cost_usd"], unit_cost_usd)]
    assert len(matches) == 1, (
        f"expected exactly one lot with unit_cost_usd=={unit_cost_usd}, "
        f"found {len(matches)}"
    )
    return matches[0]


def find_balance(balances: list, asset: str) -> dict:
    """Return the single Balance row for the asset."""
    matches = [b for b in balances if b["asset"] == asset]
    assert len(matches) == 1, (
        f"expected exactly one {asset} balance, found {len(matches)}"
    )
    return matches[0]
