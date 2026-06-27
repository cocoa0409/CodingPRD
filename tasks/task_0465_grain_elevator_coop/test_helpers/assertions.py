"""Entity assertions and domain invariant checkers (PRD §1-§3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """id (UUID, no type prefix), created_at/updated_at ISO 8601, version int >= 1
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID without prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_commodity(data: dict):
    _assert_common_fields(data)
    assert data["symbol"] in ["CORN", "SOYBEANS", "WHEAT"], f"bad symbol {data.get('symbol')!r}"
    assert isinstance(data["test_weight_lbs_per_bushel"], (int, float))
    assert isinstance(data["base_moisture_pct"], (int, float))
    assert isinstance(data["shrink_pct_per_point"], (int, float))
    assert isinstance(data["drying_cents_per_point_per_bushel"], (int, float))
    assert isinstance(data["futures_contract_bushels"], int)


def assert_price_board(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["futures_price"], (int, float))
    assert isinstance(data["cash_basis"], (int, float))
    assert isinstance(data["cash_price"], (int, float))
    assert isinstance(data["is_current"], bool)


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["equity_credit_dollars"], (int, float))
    assert isinstance(data["cash_paid_dollars"], (int, float))
    assert isinstance(data["net_priced_bushels"], (int, float))


def assert_scale_ticket(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["WEIGHED", "GRADED", "SETTLED_IN", "VOIDED"], (
        f"bad status {data.get('status')!r}"
    )
    assert data["deposit_account_type"] in ["DELAYED_PRICE", "WAREHOUSE_RECEIPT"]


def assert_storage_position(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["STORED", "CHARGE_FROZEN", "DEPLETED", "VOIDED"], (
        f"bad status {data.get('status')!r}"
    )
    assert data["program"] in ["DELAYED_PRICE", "WAREHOUSE_RECEIPT"]
    assert data["bushels_available"] >= 0, "bushels_available must be non-negative"
    assert data["bushels_available"] <= data["bushels"] + 1e-9, (
        "bushels_available cannot exceed deposited bushels"
    )


def assert_warehouse_receipt(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ISSUED", "CANCELLED"], f"bad status {data.get('status')!r}"


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert data["contract_type"] in ["CASH", "FORWARD", "BASIS", "HTA"]
    assert data["status"] in ["OPEN", "PRICED", "SETTLED", "CANCELLED"], (
        f"bad status {data.get('status')!r}"
    )


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SETTLED", "CANCELLED"], f"bad status {data.get('status')!r}"
    assert data["storage_basis"] in ["ESTIMATE", "ACTUAL"]


def assert_loadout_bay(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_dryer_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["cleanout_buffer_minutes"], int)


def assert_drying_reservation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["RESERVED", "RELEASED"], f"bad status {data.get('status')!r}"


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "LOADED", "SHIPPED", "CANCELLED"], (
        f"bad status {data.get('status')!r}"
    )


def assert_hedge_position(data: dict):
    _assert_common_fields(data)
    assert data["side"] in ["SHORT", "LONG"]
    assert data["status"] in ["OPEN", "MARGIN_CALL", "CLOSED"], f"bad status {data.get('status')!r}"
    assert isinstance(data["contracts"], int)


def assert_patronage_period(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "CLOSED"], f"bad status {data.get('status')!r}"


def assert_patronage_allocation(data: dict):
    """PatronageAllocation is append-only: id + created_at only, NO version/updated_at
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "allocation id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "PatronageAllocation must NOT carry a version field"
    assert "updated_at" not in data, "PatronageAllocation must NOT carry an updated_at field"


def assert_hedge_equity_identity(data: dict):
    """account_equity_dollars == posted_margin_dollars + unrealized_pnl_dollars
    (PRD §3.8)."""
    expected = round(data["posted_margin_dollars"] + data["unrealized_pnl_dollars"], 2)
    assert abs(data["account_equity_dollars"] - expected) < 0.005, (
        f"equity identity broken: equity {data['account_equity_dollars']} != "
        f"posted {data['posted_margin_dollars']} + pnl {data['unrealized_pnl_dollars']}"
    )
