"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_account(data: dict):
    _common_fields(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert data["credit_terms"] in ("PREPAID", "NET_15", "NET_30")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["tax_exempt_status"] in ("NONE", "CERTIFIED", "EXPIRED")
    assert isinstance(data["outstanding_cents"], int)
    assert isinstance(data["credit_available_cents"], int)
    # credit_available = credit_limit - outstanding (§2.10)
    assert data["credit_available_cents"] == data["credit_limit_cents"] - data["outstanding_cents"]


def assert_product(data: dict):
    _common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("SMALLWARE", "EQUIPMENT", "CONSUMABLE")
    assert isinstance(data["taxable"], bool)
    assert data["fulfillment_type"] in ("STOCK", "DROPSHIP")
    assert data["freight_type"] in ("PARCEL", "LTL")
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["needs_reorder"], bool)
    assert isinstance(data["reorder_suggested_qty"], int) and data["reorder_suggested_qty"] >= 0
    # needs_reorder == (on_hand_qty <= reorder_point) (§3.3)
    assert data["needs_reorder"] == (data["on_hand_qty"] <= data["reorder_point"])


def assert_order(data: dict):
    _common_fields(data)
    assert data["lifecycle_status"] in ("DRAFT", "CONFIRMED", "SHIPPED", "COMPLETED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "INVOICED", "PAID")
    assert isinstance(data["merchandise_subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["freight_cents"], int)
    assert isinstance(data["total_cents"], int)
    # total = subtotal + tax + freight (§3.4)
    assert data["total_cents"] == (
        data["merchandise_subtotal_cents"] + data["tax_cents"] + data["freight_cents"]
    ), "total_cents must equal subtotal + tax + freight"


def assert_order_line(data: dict):
    _common_fields(data)
    assert data["pricing_tier"] in ("EACH", "CASE", "PALLET")
    assert data["status"] in (
        "PENDING", "ALLOCATED", "PARTIAL", "BACKORDERED", "DROPSHIP_PENDING", "SHIPPED", "CANCELLED"
    )
    assert isinstance(data["line_subtotal_cents"], int)
    assert isinstance(data["allocated_qty"], int)
    assert isinstance(data["backordered_qty"], int)


def assert_shipment(data: dict):
    _common_fields(data)
    assert data["status"] in ("QUOTED", "BOOKED", "DELIVERED", "CANCELLED")
    assert data["shipping_mode"] in ("PARCEL", "LTL")
    assert isinstance(data["freight_quote_cents"], int)


def assert_return(data: dict):
    _common_fields(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "RECEIVED", "REFUNDED", "REJECTED")
    assert isinstance(data["restock_fee_cents"], int)
    assert isinstance(data["refund_cents"], int)


def assert_return_line(data: dict):
    _common_fields(data)
    assert data["condition"] in ("SEALED", "OPENED")
    assert data["status"] in ("PENDING", "RECEIVED")
    assert isinstance(data["line_refund_cents"], int)


def assert_certificate(data: dict):
    _common_fields(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "EXPIRED")
