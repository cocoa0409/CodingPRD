"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["tier"] in ("STANDARD", "SILVER", "GOLD")
    assert isinstance(data["store_credit_balance_cents"], int)
    assert data["store_credit_balance_cents"] >= 0, "balance is never negative"
    assert isinstance(data["loyalty_points"], int)
    assert data["loyalty_points"] >= 0, "loyalty_points never negative"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["kind"] in ("GAME", "CONSOLE", "ACCESSORY")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["base_trade_value_cents"], int) and data["base_trade_value_cents"] >= 0
    assert isinstance(data["daily_rental_rate_cents"], int) and data["daily_rental_rate_cents"] >= 0


def assert_product_stock(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert data["release_state"] in ("EMBARGOED", "RELEASED")
    for f in ("unit_price_cents", "deposit_cents", "total_count",
              "available_count", "allocated_count", "fulfilled_count"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert_stock_conservation(data)


def assert_stock_conservation(data: dict):
    """PRD §2.9: available + allocated + fulfilled == total_count, at all times."""
    assert (data["available_count"] + data["allocated_count"] + data["fulfilled_count"]
            == data["total_count"]), "unit conservation invariant violated"
    assert data["available_count"] >= 0
    assert data["allocated_count"] >= 0
    assert data["fulfilled_count"] >= 0


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert data["condition_grade"] in ("A", "B", "C", "D")
    assert data["status"] in ("AVAILABLE", "RENTED", "SOLD")
    assert isinstance(data["acquisition_cost_cents"], int) and data["acquisition_cost_cents"] >= 0


def assert_pre_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("product_stock_id", "")), "product_stock_id must be a UUID"
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED")
    assert data["allocation_status"] in (
        "PENDING", "WAITLISTED", "ALLOCATED", "FULFILLED", "RELEASED")
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0


def assert_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "CONSUMED", "RELEASED")


def assert_trade_in(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert data["stated_grade"] in ("A", "B", "C", "D")
    assert data["payout_method"] in ("CASH", "STORE_CREDIT")
    assert data["status"] in ("SUBMITTED", "OFFERED", "DISPUTED", "SETTLED", "VOIDED")
    assert isinstance(data["provisional_value_cents"], int)


def assert_rental(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("inventory_item_id", "")), "inventory_item_id must be a UUID"
    assert data["status"] in ("RESERVED", "CHECKED_OUT", "RETURNED")
    assert isinstance(data["daily_rate_cents"], int)
    assert isinstance(data["planned_days"], int)


def assert_sale(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    for f in ("subtotal_cents", "tax_total_cents", "total_cents",
              "amount_due_cents", "loyalty_points_earned"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["amount_due_cents"] >= 0


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] > 0


def assert_tournament(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", "")), "station_id must be a UUID"
    assert isinstance(data["max_participants"], int) and data["max_participants"] > 0
    assert isinstance(data["registered_count"], int)
    assert data["registered_count"] <= data["max_participants"], "count never exceeds capacity"
    assert isinstance(data["registered_member_ids"], list)


def assert_store_credit_entry(data: dict):
    """PRD §2.4: append-only ledger event carries only id + created_at (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "StoreCreditEntry must NOT carry a version"
    assert "updated_at" not in data, "StoreCreditEntry must NOT carry updated_at"
    assert data["reason"] in (
        "TRADE_IN_PAYOUT", "TRADE_IN_VOID_REVERSAL", "MANUAL_ADJUSTMENT",
        "SALE_REDEMPTION", "PREORDER_REFUND")
    assert isinstance(data["amount_cents"], int)
