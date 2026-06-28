"""Entity assertions and domain invariant checkers for the Spin Studio API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id (UUID, no type prefix), created_at/updated_at (ISO8601), version (int)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_studio(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["city"], str) and len(data["city"]) > 0
    assert isinstance(data["late_cancel_window_minutes"], int)
    assert isinstance(data["late_cancel_fee_cents"], int)
    assert isinstance(data["no_show_fee_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["studio_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["bike_count"], int) and data["bike_count"] >= 0
    assert data["status"] == "OPEN"


def assert_bike(data: dict):
    _assert_common(data)
    assert isinstance(data["room_id"], str)
    assert isinstance(data["position_row"], int) and data["position_row"] >= 1
    assert isinstance(data["position_col"], int) and data["position_col"] >= 1
    assert isinstance(data["label"], str)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert data["status"] == "ACTIVE"


def assert_session(data: dict):
    _assert_common(data)
    assert isinstance(data["studio_id"], str)
    assert isinstance(data["room_id"], str)
    assert isinstance(data["instructor_id"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert isinstance(data["waitlist_count"], int) and data["waitlist_count"] >= 0
    assert isinstance(data["waitlist_capacity"], int)
    assert data["status"] in ("SCHEDULED", "CANCELLED", "COMPLETED")


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["home_studio_id"], str)
    assert isinstance(data["completed_ride_count"], int) and data["completed_ride_count"] >= 0
    assert isinstance(data["active_strike_count"], int) and data["active_strike_count"] >= 0
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["account_status"] in ("ACTIVE", "SUSPENDED")


def assert_credit_pack(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert data["kind"] in ("CLASS_PACK", "MEMBERSHIP")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["remaining_credits"], int)
    assert data["scope"] in ("HOME_ONLY", "MULTI_STUDIO")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED", "REFUNDED")


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["bike_id"], str)
    assert data["attendance_status"] in (
        "BOOKED", "ATTENDED", "LATE_CANCELLED", "EARLY_CANCELLED", "NO_SHOW",
    )
    assert data["billing_status"] in (
        "CREDIT_HELD", "CREDIT_CONSUMED", "CREDIT_REFUNDED", "FEE_CHARGED",
    )
    assert isinstance(data["first_ride_discount_applied"], bool)
    assert data["shoe_status"] in ("NONE", "RESERVED", "RETURNED", "FORFEITED")
    assert isinstance(data["shoe_fee_cents"], int)


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["member_id"], str)
    assert data["status"] in ("WAITING", "PROMOTED", "EXPIRED_OFF", "CANCELLED")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["studio_id"], str)
    assert isinstance(data["sku"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0
    assert data["status"] in ("AVAILABLE", "DISCONTINUED")


def assert_retail_order(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["studio_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["wallet_applied_cents"], int)
    assert isinstance(data["card_charged_cents"], int)
    assert data["status"] == "PLACED"


def assert_penalty_charge(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["reservation_id"], str)
    assert data["kind"] in ("LATE_CANCEL", "NO_SHOW")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["counts_as_strike"], bool)
    assert isinstance(data["waived"], bool)
