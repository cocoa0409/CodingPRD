"""Entity assertions and small parsing utilities (PRD sections 2.2, 2.4, 3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (with or without fractional digits / Z)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def instants_equal(a: str, b: str) -> bool:
    return parse_instant(a) == parse_instant(b)


def date_component(value: str) -> str:
    """Return the YYYY-MM-DD date component of an ISO date/datetime string."""
    return str(value)[:10]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["account_type"] in ("CORPORATE", "RETAIL")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["default_warehouse_code"] in ("ATL", "RNO", "DFW")
    assert isinstance(data["open_receivable_cents"], int) and data["open_receivable_cents"] >= 0


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("BOXES", "MAILERS", "TAPE", "CUSHIONING", "LABELS")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert data["uom"] in ("EACH", "CASE")
    assert isinstance(data["case_qty"], int) and data["case_qty"] >= 1
    assert isinstance(data["pallet_qty"], int) and data["pallet_qty"] >= 1
    assert data["weight_lbs_per_unit"] > 0
    assert data["density_pcf"] >= 1
    assert data["ship_method"] in ("PARCEL", "FREIGHT")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_warehouse(data: dict):
    _assert_common_fields(data)
    assert data["code"] in ("ATL", "RNO", "DFW")
    assert 1 <= data["zone"] <= 8
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_inventory(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["available_qty"], int)
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        "available_qty must always equal on_hand_qty - reserved_qty (PRD section 3.3)"
    )


def assert_quantity_break(data: dict):
    # Quantity breaks carry only id and created_at; updated_at/version are absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "quantity break must not carry updated_at"
    assert "version" not in data, "quantity break must not carry version"
    assert isinstance(data["min_qty"], int) and data["min_qty"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert data["status"] in (
        "DRAFT", "PENDING", "PO_REVIEW", "STOCK_RESERVED", "CUSTOM_PRODUCTION",
        "SHIPPED", "PARTIALLY_BACKORDERED", "CANCELLED", "RETURNED",
    )
    assert 1 <= data["ship_zone"] <= 8
    for field in ("subtotal_cents", "pallet_discount_cents", "oversize_surcharge_cents",
                  "freight_estimate_cents", "grand_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["invoice_status"] in ("OPEN", "PAID", "VOID")


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["status"] in (
        "OPEN", "ALLOCATED", "IN_PRODUCTION", "SHIPPED", "BACKORDERED", "CANCELLED",
    )
    assert isinstance(data["shipped_qty"], int) and data["shipped_qty"] >= 0


def assert_custom_print_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_line_id"])
    assert data["status"] in ("QUEUED", "PLATING", "PRINTING", "COMPLETED", "SCRAPPED")


def assert_return(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["return_type"] in ("STOCK", "CUSTOM")
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "RECEIVED", "RESTOCKED")
    assert isinstance(data["restock_fee_cents"], int) and data["restock_fee_cents"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0


def assert_return_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["return_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1


def assert_restock_notification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["status"] in ("ACTIVE", "NOTIFIED", "CANCELLED")
