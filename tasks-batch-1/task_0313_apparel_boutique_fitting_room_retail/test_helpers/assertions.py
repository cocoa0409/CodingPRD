"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common audit fields carried by every mutable resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_boutique(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_rate_bps"], int)
    assert 0 <= data["tax_rate_bps"] <= 2000
    assert isinstance(data["current_business_date"], int)
    assert isinstance(data["return_window_days"], int)
    assert data["return_window_days"] >= 0
    assert isinstance(data["store_credit_outstanding_cents"], int)
    assert data["store_credit_outstanding_cents"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store credit wallet is never negative"
    assert isinstance(data["loyalty_points"], int)
    assert data["loyalty_points"] >= 0, "net loyalty points are never below 0"
    assert isinstance(data["captured_spend_cents"], int)
    assert data["loyalty_tier"] in ("STANDARD", "SILVER", "GOLD")


def assert_style(data: dict):
    _assert_common(data)
    assert isinstance(data["style_code"], str) and len(data["style_code"]) > 0
    assert data["category"] in ("TOPS", "BOTTOMS", "DRESSES", "OUTERWEAR", "ACCESSORIES")
    assert data["season"] in ("SPRING", "SUMMER", "FALL", "WINTER")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["current_price_cents"], int)
    assert isinstance(data["clearance"], bool)
    assert isinstance(data["total_available"], int)
    assert data["total_available"] >= 0


def assert_sku_variant(data: dict):
    _assert_common(data)
    assert data["size"] in ("XS", "S", "M", "L", "XL")
    assert isinstance(data["color"], str)
    for field in ("on_hand", "reserved", "available"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never be negative"
    assert data["status"] in ("STOCKED", "DISCONTINUED")
    assert_inventory_conservation(data)


def assert_inventory_conservation(data: dict):
    """The conservation invariant: available == on_hand - reserved, never negative."""
    assert data["available"] == data["on_hand"] - data["reserved"], (
        f"available ({data['available']}) must equal on_hand ({data['on_hand']}) "
        f"minus reserved ({data['reserved']})"
    )
    assert data["available"] >= 0, "available is never negative"


def assert_fitting_room(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_hold(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXTENDED", "CONVERTED", "EXPIRED", "RELEASED")
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert 0 <= data["start_minute"] < 1440
    assert data["start_minute"] < data["end_minute"] <= 1440


def assert_stylist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert data["status"] in ("ACTIVE", "OFF")


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert 0 <= data["start_minute"] < 1440
    assert data["start_minute"] < data["end_minute"] <= 1440


def assert_markdown_schedule(data: dict):
    _assert_common(data)
    assert data["phase"] in ("SEASONAL", "CLEARANCE")
    assert isinstance(data["markdown_pct"], int)
    assert 1 <= data["markdown_pct"] <= 90
    assert isinstance(data["effective_date"], int) and data["effective_date"] >= 0
    assert data["status"] in ("DRAFT", "SCHEDULED", "ACTIVE", "ENDED", "SUPERSEDED")


def assert_sales_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED", "REFUNDED")
    assert data["fulfillment_status"] in ("OPEN", "COMPLETED", "CANCELLED")
    for field in ("subtotal_cents", "loyalty_discount_cents", "tax_cents",
                  "store_credit_applied_cents", "total_cents", "points_earned"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["line_total_cents"] == data["unit_price_cents"] * data["qty"]
    assert data["status"] in ("SOLD", "RETURNED", "EXCHANGED")


def assert_return_request(data: dict):
    _assert_common(data)
    assert data["resolution"] in ("REFUND", "EXCHANGE")
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "VOIDED")
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert isinstance(data["points_reversed"], int) and data["points_reversed"] >= 0


def assert_special_order(data: dict):
    _assert_common(data)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["status"] in ("PLACED", "SOURCED", "SHIPPED", "DELIVERED", "CANCELLED")
    assert isinstance(data["reserved_units"], int) and data["reserved_units"] >= 0


def assert_lookbook(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert data["season"] in ("SPRING", "SUMMER", "FALL", "WINTER")
    assert isinstance(data["style_ids"], list)
    assert data["status"] in ("DRAFT", "PUBLISHED")
    assert isinstance(data["featured_count"], int) and data["featured_count"] >= 0
