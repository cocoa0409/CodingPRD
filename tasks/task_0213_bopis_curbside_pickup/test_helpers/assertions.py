"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_FULFILLMENT_STATES = {
    "DRAFT", "SUBMITTED", "PICKING", "STAGED", "AWAITING_PICKUP",
    "PARTIALLY_PICKED_UP", "COMPLETED", "CANCELLED", "EXPIRED",
}
_PAYMENT_STATES = {
    "UNAUTHORIZED", "AUTHORIZED", "CAPTURED", "REFUNDED", "PARTIALLY_REFUNDED",
}
_LINE_STATES = {
    "PENDING", "RESERVED", "SHORT_PICKED", "PICKED", "SUBSTITUTION_PROPOSED",
    "SUBSTITUTED", "HANDED_OVER", "NOT_FULFILLED",
}
_SUB_STATES = {"PROPOSED", "ACCEPTED", "DECLINED", "WITHDRAWN"}
_HOLD_STATES = {"ACTIVE", "RELEASED", "EXPIRED"}
_CHECKIN_STATES = {"ARRIVED", "BEING_LOADED", "COMPLETED", "CANCELLED"}
_FILL_STATES = {"OPEN", "FULL"}
_STANDING_STATES = {"GOOD", "WATCH", "BLOCKED"}
_MOVEMENT_TYPES = {"RESTOCK", "RESERVE", "RELEASE", "PICK_REMOVE"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["phone"], str) and len(data["phone"]) > 0
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["pickup_standing"] in _STANDING_STATES, data.get("pickup_standing")


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["curbside_spaces"], int) and data["curbside_spaces"] >= 1
    assert isinstance(data["hold_window_minutes"], int) and data["hold_window_minutes"] >= 1
    assert isinstance(data["active_curbside_count"], int) and data["active_curbside_count"] >= 0


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert data["substitution_group"] is None or (
        isinstance(data["substitution_group"], str) and len(data["substitution_group"]) > 0
    )


def assert_store_inventory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["on_hand"], int) and data["on_hand"] >= 0
    assert isinstance(data["reserved"], int) and data["reserved"] >= 0
    assert isinstance(data["available"], int) and data["available"] >= 0
    assert_inventory_invariants(data)


def assert_inventory_invariants(data: dict):
    """available == max(0, on_hand - reserved) (PRD §2.6)."""
    expected_available = max(0, data["on_hand"] - data["reserved"])
    assert data["available"] == expected_available, (
        f"available should be max(0, on_hand - reserved) = {expected_available}, "
        f"got {data['available']} (on_hand={data['on_hand']}, reserved={data['reserved']})"
    )


def assert_pickup_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["cutoff_offset_minutes"], int) and data["cutoff_offset_minutes"] >= 0
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["booked_count"], int) and 0 <= data["booked_count"] <= data["capacity"]
    assert data["fill_status"] in _FILL_STATES, data.get("fill_status")
    assert_slot_fill_invariant(data)


def assert_slot_fill_invariant(data: dict):
    """fill_status == FULL iff booked_count >= capacity (PRD §2.7)."""
    expected = "FULL" if data["booked_count"] >= data["capacity"] else "OPEN"
    assert data["fill_status"] == expected, (
        f"fill_status should be {expected} for booked_count={data['booked_count']}, "
        f"capacity={data['capacity']}, got {data['fill_status']}"
    )


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["store_id"])
    assert data["fulfillment_status"] in _FULFILLMENT_STATES, data.get("fulfillment_status")
    assert data["payment_status"] in _PAYMENT_STATES, data.get("payment_status")
    assert isinstance(data["authorized_total_cents"], int) and data["authorized_total_cents"] >= 0
    assert isinstance(data["captured_total_cents"], int) and data["captured_total_cents"] >= 0
    assert isinstance(data["refunded_total_cents"], int) and data["refunded_total_cents"] >= 0
    assert isinstance(data["verified"], bool)


def assert_money_conserved_on_completion(data: dict):
    """For a COMPLETED order: captured + refunded == authorized (PRD §3.9 invariant)."""
    assert data["captured_total_cents"] + data["refunded_total_cents"] == data["authorized_total_cents"], (
        f"captured ({data['captured_total_cents']}) + refunded ({data['refunded_total_cents']}) "
        f"must equal authorized ({data['authorized_total_cents']})"
    )


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["qty_ordered"], int) and data["qty_ordered"] > 0
    assert isinstance(data["qty_reserved"], int) and 0 <= data["qty_reserved"] <= data["qty_ordered"]
    assert isinstance(data["qty_picked"], int) and 0 <= data["qty_picked"] <= data["qty_ordered"]
    assert isinstance(data["qty_handed_over"], int) and 0 <= data["qty_handed_over"] <= data["qty_picked"]
    assert data["line_status"] in _LINE_STATES, data.get("line_status")


def assert_substitution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_line_id"])
    assert is_valid_uuid(data["substitute_product_id"])
    assert isinstance(data["substitute_qty"], int) and data["substitute_qty"] > 0
    assert data["decision_status"] in _SUB_STATES, data.get("decision_status")
    assert isinstance(data["price_delta_cents"], int)


def assert_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["store_id"])
    assert is_iso8601_timestamp(data["staged_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["hold_status"] in _HOLD_STATES, data.get("hold_status")


def assert_curbside_checkin(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["vehicle_description"], str) and len(data["vehicle_description"]) > 0
    assert data["checkin_status"] in _CHECKIN_STATES, data.get("checkin_status")


def assert_pickup_event(data: dict):
    """Append-only ledger entry: id + created_at only (PRD §2.4); no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert isinstance(data["qty_handed_over"], int) and data["qty_handed_over"] > 0
    assert isinstance(data["captured_cents"], int) and data["captured_cents"] >= 0


def assert_pickup_event_is_ledger(data: dict):
    """PickupEvent carries neither updated_at nor version (PRD §2.4)."""
    assert "updated_at" not in data, "PickupEvent must not carry updated_at (immutable ledger)"
    assert "version" not in data, "PickupEvent must not carry version (immutable ledger)"


def assert_inventory_movement(data: dict):
    """Append-only ledger entry: id + created_at only (PRD §2.4); no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["store_inventory_id"])
    assert data["movement_type"] in _MOVEMENT_TYPES, data.get("movement_type")
    assert isinstance(data["delta_on_hand"], int)
    assert isinstance(data["delta_reserved"], int)
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
