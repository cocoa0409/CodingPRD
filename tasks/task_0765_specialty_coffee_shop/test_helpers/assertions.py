"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_bean_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["origin"], str) and len(data["origin"]) > 0
    assert data["roast_level"] in ("LIGHT", "MEDIUM", "DARK")
    assert data["rotation_status"] in ("RESERVE", "ACTIVE", "DEPLETED")
    for f in ("received_grams", "consumed_grams", "waste_grams_total",
              "on_hand_grams", "par_grams", "price_per_gram_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["on_hand_grams"] >= 0, "on_hand_grams never negative"
    assert isinstance(data["reorder_needed"], bool)


def assert_menu_item(data: dict):
    _assert_common(data)
    assert data["category"] in ("BEVERAGE", "FOOD", "RETAIL_BAG")
    assert data["size"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["required_equipment_type"] in ("ESPRESSO", "BATCH_BREW", "GRINDER", "NONE")
    assert data["availability"] in ("AVAILABLE", "UNAVAILABLE")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0


def assert_equipment(data: dict):
    _assert_common(data)
    assert data["equipment_type"] in ("ESPRESSO", "BATCH_BREW", "GRINDER")
    assert data["status"] in ("OPERATIONAL", "NEEDS_CALIBRATION", "IN_MAINTENANCE")
    assert isinstance(data["shots_since_calibration"], int)
    assert isinstance(data["needs_calibration"], bool)


def assert_member(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0
    assert isinstance(data["lifetime_points"], int) and data["lifetime_points"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("PLACED", "FULFILLED", "VOIDED")
    for f in ("subtotal_cents", "service_fee_cents", "discount_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["total_cents"] >= 0, "total_cents floored at zero"
    assert isinstance(data["points_earned_provisional"], int)


def assert_catering_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "CONFIRMED", "CANCELLED")
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["deposit_cents"], int)


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "CANCELLED")
    assert data["frequency"] in ("WEEKLY", "BIWEEKLY", "MONTHLY")


def assert_reconciliation(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "COUNTING", "CLOSED")
    assert isinstance(data["opening_bean_on_hand_grams"], int)
