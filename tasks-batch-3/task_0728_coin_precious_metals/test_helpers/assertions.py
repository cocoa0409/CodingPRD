"""Entity assertions and domain invariant checkers.

Every persisted resource carries id (UUID), created_at (ISO 8601), updated_at,
and an integer version. Money fields are integer cents.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_spot_rate(data: dict):
    _assert_common(data)
    assert data["metal"] in ("GOLD", "SILVER", "PLATINUM", "PALLADIUM")
    assert isinstance(data["price_per_troy_oz_cents"], int)
    assert data["price_per_troy_oz_cents"] >= 1


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["product_type"] in ("BULLION", "NUMISMATIC")
    assert data["metal"] in ("GOLD", "SILVER", "PLATINUM", "PALLADIUM")
    assert isinstance(data["numismatic_premium_cents"], int)
    assert data["numismatic_premium_cents"] >= 0
    assert isinstance(data["ira_eligible"], bool)


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "DEPLETED")
    for f in ("total_qty", "available_qty", "reserved_qty", "sold_qty", "acquisition_unit_cost_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert_inventory_lot_invariants(data)


def assert_inventory_lot_invariants(data: dict):
    """Standing invariant: available_qty + reserved_qty + sold_qty == total_qty."""
    assert data["available_qty"] >= 0
    assert data["reserved_qty"] >= 0
    assert data["sold_qty"] >= 0
    assert (
        data["available_qty"] + data["reserved_qty"] + data["sold_qty"] == data["total_qty"]
    ), "available_qty + reserved_qty + sold_qty must equal total_qty"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["id_document_on_file"], bool)
    assert isinstance(data["lifetime_buy_payout_cents"], int)
    assert isinstance(data["store_credit_cents"], int)


def assert_ira_account(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "CLOSED")
    assert isinstance(data["allocated_value_cents"], int)


def assert_sell_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLACED", "SETTLED", "CANCELLED")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["quoted_unit_price_cents"], int)
    assert isinstance(data["total_price_cents"], int)


def assert_buy_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLACED", "SETTLED", "REJECTED")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["quoted_unit_payout_cents"], int)
    assert isinstance(data["total_payout_cents"], int)
    assert isinstance(data["reportable"], bool)


def assert_layaway(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED")
    assert isinstance(data["locked_unit_price_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_consignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("INTAKE", "LISTED", "SOLD", "RETURNED")
    assert isinstance(data["reserve_price_cents"], int)


def assert_hedge_position(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["entry_spot_cents"], int)


def assert_settlement(data: dict):
    _assert_common(data)
    for f in ("hammer_price_cents", "commission_cents", "buyer_premium_cents",
              "seller_proceeds_cents", "dealer_revenue_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_appraiser(data: dict):
    _assert_common(data)
    assert data["specialty_metal"] in ("GOLD", "SILVER", "PLATINUM", "PALLADIUM")


def assert_appraisal_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "CANCELLED")


def assert_auction_session(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CLOSED")
