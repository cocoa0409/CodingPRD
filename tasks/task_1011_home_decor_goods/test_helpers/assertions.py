"""Entity assertions and domain invariant checkers for the store API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["status"] in ("ACTIVE", "RESET_LOCKED")
    assert isinstance(data["oversized_slots_per_day"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert data["markdown_tier"] in ("FULL", "MARKDOWN_1", "MARKDOWN_2", "CLEARANCE")
    assert isinstance(data["weeks_on_shelf"], int) and data["weeks_on_shelf"] >= 0
    assert isinstance(data["current_price_cents"], int)
    assert data["current_price_cents"] >= data["clearance_floor_cents"]


def assert_store_inventory(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DEAD")
    assert_inventory_conserved(data)


def assert_inventory_conserved(data: dict):
    """PRD §2.7: allocated_qty == on_hand_qty + reserved_qty + sold_qty; on_hand >= 0."""
    assert data["on_hand_qty"] >= 0, "on_hand_qty must never go below zero"
    total = data["on_hand_qty"] + data["reserved_qty"] + data["sold_qty"]
    assert data["allocated_qty"] == total, (
        f"inventory conservation violated: allocated {data['allocated_qty']} != "
        f"on_hand {data['on_hand_qty']} + reserved {data['reserved_qty']} + sold {data['sold_qty']}"
    )


def assert_loyalty_member(data: dict):
    _assert_common(data)
    assert data["tier"] in ("STANDARD", "SILVER", "GOLD")
    assert data["status"] == "ACTIVE"
    assert_points_conserved(data)


def assert_points_conserved(data: dict):
    """PRD §2.7: points_balance == points_earned_total - points_redeemed_total; balance >= 0."""
    assert data["points_balance"] >= 0, "points_balance must never go below zero"
    assert data["points_balance"] == data["points_earned_total"] - data["points_redeemed_total"], (
        f"points conservation violated: balance {data['points_balance']} != "
        f"earned {data['points_earned_total']} - redeemed {data['points_redeemed_total']}"
    )


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in ("PENDING", "READY", "FULFILLED", "CANCELLED")
    assert data["payment_status"] in ("AUTHORIZED", "CAPTURED", "REFUNDED", "VOIDED")


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_net_cents"], int)


def assert_delivery_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_return(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED")
    assert data["variant"] in ("RECEIPTED", "NON_RECEIPTED")


def assert_registry(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_registry_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "UNAVAILABLE")


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "QUOTED", "CUSTOMER_REVIEW", "CONFIRMED", "CANCELLED")
