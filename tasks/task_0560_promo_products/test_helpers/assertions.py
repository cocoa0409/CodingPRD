"""Entity assertions for the Promo Products API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

DECORATION_METHODS = ["SCREEN_PRINT", "EMBROIDERY", "LASER_ENGRAVE"]
STATION_TYPES = ["SCREEN_PRESS", "EMBROIDERY_MACHINE", "LASER"]
ORDER_FULFILLMENT_STATES = [
    "DRAFT", "QUOTED", "CONFIRMED", "IN_PRODUCTION", "SHIPPED", "DELIVERED", "CANCELLED",
]
ORDER_PAYMENT_STATES = ["UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED"]
ORDER_LINE_STATES = [
    "PENDING_ART", "ART_READY", "CONFIRMED", "SCHEDULED",
    "PRINTING", "QC_HOLD", "COMPLETED", "CANCELLED",
]
ART_PROOF_STATES = ["DRAFT", "PENDING_APPROVAL", "CHANGES_REQUESTED", "APPROVED", "SUPERSEDED"]
PURCHASE_ORDER_STATES = ["DRAFT", "ISSUED", "RECEIVED", "CANCELLED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_mutable_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_supplier(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["blank_unit_cost_cents"], int)
    assert isinstance(data["concurrent_capacity_units"], int)
    assert isinstance(data["reserved_blank_qty"], int)
    assert data["reserved_blank_qty"] >= 0, "reserved_blank_qty must be non-negative"


def assert_product(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["sku"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["min_order_qty"], int)


def assert_price_tier(data: dict):
    # Immutable configuration: only id + created_at guaranteed.
    _assert_common(data)
    assert data["decoration_method"] in DECORATION_METHODS
    assert isinstance(data["min_quantity"], int)
    assert isinstance(data["unit_price_cents"], int)


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["station_type"] in STATION_TYPES


def assert_customer(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["total_funded_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)


def assert_order(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["order_type"] in ["STANDARD", "SAMPLE", "REORDER"]
    assert data["fulfillment_status"] in ORDER_FULFILLMENT_STATES
    assert data["payment_status"] in ORDER_PAYMENT_STATES
    assert isinstance(data["escrow_cents"], int)


def assert_order_line(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["product_id"], str)
    assert data["decoration_method"] in DECORATION_METHODS
    assert isinstance(data["quantity"], int)
    assert data["status"] in ORDER_LINE_STATES


def assert_art_proof(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["proof_url"], str)
    assert data["status"] in ART_PROOF_STATES


def assert_purchase_order(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["ordered_blank_qty"], int)
    assert data["status"] in PURCHASE_ORDER_STATES


def assert_shipment(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["carrier"], str)
