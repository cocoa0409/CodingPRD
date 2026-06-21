"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for primary resources."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["tax_rate_bps"], int)
    assert 0 <= data["tax_rate_bps"] <= 2000
    assert isinstance(data["loyalty_earn_rate_bps"], int) and data["loyalty_earn_rate_bps"] >= 0
    assert data["posture"] in ("DRAWER_OPEN", "LOCKED")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["barcode"], str) and len(data["barcode"]) > 0
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["tax_exempt"], bool)
    assert isinstance(data["loyalty_eligible"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["available_qty"], int)
    assert isinstance(data["reorder_point"], int) and data["reorder_point"] >= 0
    assert isinstance(data["below_reorder"], bool)
    assert_inventory_invariants(data)


def assert_inventory_invariants(data: dict):
    """available_qty == on_hand_qty - reserved_qty; below_reorder == (available <= reorder_point)."""
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        "available_qty must equal on_hand_qty - reserved_qty"
    )
    assert data["below_reorder"] == (data["available_qty"] <= data["reorder_point"]), (
        "below_reorder must be true iff available_qty <= reorder_point (inclusive)"
    )


def assert_loyalty_account(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_name"], str) and len(data["customer_name"]) > 0
    assert isinstance(data["phone"], str) and len(data["phone"]) > 0
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0
    assert isinstance(data["lifetime_points"], int) and data["lifetime_points"] >= 0
    assert data["tier"] in ("STANDARD", "SILVER", "GOLD")


def assert_promotion(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["kind"] in ("PERCENT_OFF", "AMOUNT_OFF", "BOGO_50")
    assert isinstance(data["value"], int) and data["value"] >= 0
    assert isinstance(data["min_subtotal_cents"], int) and data["min_subtotal_cents"] >= 0
    assert isinstance(data["stackable"], bool)
    assert data["status"] in ("ACTIVE", "DISABLED")


def assert_cash_session(data: dict):
    _assert_common(data)
    assert isinstance(data["opening_float_cents"], int) and data["opening_float_cents"] >= 0
    assert isinstance(data["expected_cash_cents"], int)
    assert data["status"] in ("OPEN", "CLOSE_REQUESTED", "RECONCILED", "FORCE_CLOSED")


def assert_sale(data: dict):
    _assert_common(data)
    assert data["kind"] in ("SALE", "RETURN", "EXCHANGE")
    assert data["settlement_status"] in ("DRAFT", "TENDERING", "SETTLED", "VOIDED")
    assert data["stock_status"] in ("PENDING", "COMMITTED", "RESTOCKED")
    assert isinstance(data["merchandise_subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["loyalty_redeemed_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["tendered_cents"], int)
    assert isinstance(data["points_earned"], int)


def assert_tender_line(data: dict):
    """TenderLine is append-only: only id + created_at, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "TenderLine is immutable: it must carry no version field"
    assert "updated_at" not in data, "TenderLine is immutable: it must carry no updated_at field"
    assert data["method"] in ("CASH", "CARD", "STORE_CREDIT", "GIFT_CARD")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["change_due_cents"], int)


def assert_layaway(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["total_price_cents"], int) and data["total_price_cents"] >= 0
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ("ACTIVE", "DELINQUENT", "FULFILLED", "FORFEITED", "CANCELLED")


def assert_transfer(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("REQUESTED", "DISPATCHED", "RECEIVED", "REJECTED", "CANCELLED")


def assert_count_sheet(data: dict):
    _assert_common(data)
    assert isinstance(data["counted_qty"], int) and data["counted_qty"] >= 0
    assert isinstance(data["snapshot_on_hand_qty"], int)
    assert data["status"] in ("DRAFT", "POSTED", "DISCARDED")
