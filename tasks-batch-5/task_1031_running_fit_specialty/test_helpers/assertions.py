"""Entity assertions and domain invariant checkers (PRD Sections 2-3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["loyalty_points_balance"], int)
    assert data["loyalty_points_balance"] >= 0, "loyalty_points_balance never below 0"
    assert isinstance(data["tier_qualifying_spend_cents"], int)
    assert data["loyalty_tier"] in ("STANDARD", "SILVER", "GOLD")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ("SHOE", "NUTRITION", "GEAR", "APPAREL")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["stock_on_hand"], int)
    assert isinstance(data["stock_reserved"], int)
    assert data["available_units"] == data["stock_on_hand"] - data["stock_reserved"]
    expected_avail = "IN_STOCK" if data["stock_on_hand"] > 0 else "OUT_OF_STOCK"
    assert data["availability"] == expected_avail


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in (
        "PENDING",
        "RESERVED",
        "FULFILLED",
        "RETURNED",
        "CANCELLED",
    )
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_gross_cents"] == data["unit_price_cents"] * data["quantity"]
    assert isinstance(data["is_returned"], bool)


def assert_wear_return(data: dict):
    _assert_common(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["member_id"], str)
    assert data["status"] in (
        "REQUESTED",
        "UNDER_INSPECTION",
        "APPROVED",
        "REJECTED",
        "WITHDRAWN",
    )


def assert_subscription(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert data["plan"] in ("BASIC", "PLUS", "ELITE")
    assert data["status"] in ("ACTIVE", "PAST_DUE", "CANCELLED")


def assert_running_shoe(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["retirement_threshold_miles"], int)
    assert isinstance(data["total_mileage_miles"], int)
    assert data["status"] in ("ACTIVE", "RETIREMENT_DUE", "RETIRED")


def assert_fitter(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["is_active"], bool)


def assert_fitment_session(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["fitter_id"], str)
    assert data["status"] in (
        "SCHEDULED",
        "CHECKED_IN",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )


def assert_training_session(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int)
    assert data["available_slots"] == data["capacity"] - data["booked_count"]


def assert_training_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["member_id"], str)
    assert data["status"] in (
        "BOOKED",
        "WAITLISTED",
        "CANCELLED",
        "ATTENDED",
        "NO_SHOW",
    )
