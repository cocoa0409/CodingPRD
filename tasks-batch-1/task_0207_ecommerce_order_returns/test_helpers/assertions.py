"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the system-managed fields and the field set the PRD
declares for that entity. CreditLedgerEntry is asserted WITHOUT version/updated_at
because the PRD declares it an immutable audit record carrying only id/created_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

PAYMENT_STATUSES = ["CART", "AUTHORIZED", "CAPTURED", "VOIDED",
                    "PARTIALLY_REFUNDED", "REFUNDED"]
FULFILLMENT_STATUSES = ["UNFULFILLED", "PARTIALLY_SHIPPED", "SHIPPED",
                        "PARTIALLY_DELIVERED", "DELIVERED", "BACKORDERED"]
RESERVATION_STATUSES = ["HELD", "COMMITTED", "RELEASED"]
SHIPMENT_STATUSES = ["PENDING", "SHIPPED", "DELIVERED", "CANCELLED"]
RETURN_STATUSES = ["REQUESTED", "APPROVED", "REJECTED", "REFUNDED",
                   "EXCHANGED", "RESTOCKED", "CANCELLED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store_credit_cents never negative"
    assert isinstance(data["lifetime_purchased_cents"], int)
    assert isinstance(data["lifetime_refunded_cents"], int)
    assert isinstance(data["return_risk_score"], (int, float))


def assert_warehouse(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["fulfillment_priority"], int)
    assert data["fulfillment_priority"] >= 1
    assert isinstance(data["accepts_returns"], bool)


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["title"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["tax_rate_bps"], int) and data["tax_rate_bps"] >= 0
    assert isinstance(data["restocking_fee_bps"], int)
    assert 0 <= data["restocking_fee_bps"] <= 10000
    assert isinstance(data["return_window_days"], int) and data["return_window_days"] >= 0
    assert isinstance(data["final_sale"], bool)


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert data["reserved_qty"] <= data["on_hand_qty"], "reserved_qty never exceeds on_hand_qty"
    assert isinstance(data["available_qty"], int) and data["available_qty"] >= 0
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], \
        "available_qty == on_hand_qty - reserved_qty"


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["payment_status"] in PAYMENT_STATUSES
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    for f in ("promo_flat_cents", "subtotal_cents", "discounted_subtotal_cents",
              "tax_total_cents", "shipping_fee_cents", "grand_total_cents",
              "captured_total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
        assert data[f] >= 0, f"{f} must be non-negative"


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents_snapshot"], int)
    assert isinstance(data["tax_rate_bps_snapshot"], int)
    for f in ("line_tax_cents", "reserved_qty", "backordered_qty",
              "shipped_qty", "returned_qty"):
        assert isinstance(data[f], int), f"{f} must be integer"


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_line_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["status"] in RESERVATION_STATUSES


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert data["status"] in SHIPMENT_STATUSES


def assert_shipment_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["shipment_id"])
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1


def assert_return_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in RETURN_STATUSES
    assert data["reason"] in ["DEFECTIVE", "WRONG_ITEM", "NO_LONGER_WANTED", "ARRIVED_LATE"]
    assert data["resolution"] in ["REFUND", "STORE_CREDIT", "EXCHANGE"]
    for f in ("refund_subtotal_cents", "restocking_fee_cents", "settlement_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_return_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["return_authorization_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert isinstance(data["return_qty"], int) and data["return_qty"] >= 1


def assert_refund(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["return_authorization_id"])
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["destination"] in ["ORIGINAL_PAYMENT", "STORE_CREDIT"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0, \
        "Refund.amount_cents may not be negative"
    assert data["status"] == "SETTLED", "Refund is created already SETTLED"


def assert_credit_ledger_entry(data: dict):
    """CreditLedgerEntry is an immutable audit record: id + created_at only.
    It carries NO updated_at and NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "CreditLedgerEntry has no version"
    assert "updated_at" not in data, "CreditLedgerEntry has no updated_at"
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["kind"] in ["REFUND_CREDIT", "ADMIN_ADJUSTMENT", "REDEMPTION"]
