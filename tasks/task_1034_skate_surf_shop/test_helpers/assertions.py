"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. All field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert data["category"] in [
        "DECK", "TRUCKS", "WHEELS", "GRIP", "WAX", "COMPLETE",
        "SURFBOARD", "WETSUIT", "ACCESSORY",
    ]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["available_qty"], int)
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]
    assert_product_availability(data)


def assert_product_availability(data: dict):
    """available_qty == on_hand_qty - reserved_qty; neither derived qty negative
    under valid transitions (PRD Section 2.6)."""
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        f"available_qty {data['available_qty']} != on_hand {data['on_hand_qty']} "
        f"- reserved {data['reserved_qty']}"
    )
    assert data["reserved_qty"] >= 0
    assert data["available_qty"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert isinstance(data["lifetime_spend_cents"], int) and data["lifetime_spend_cents"] >= 0
    assert isinstance(data["store_credit_cents"], int) and data["store_credit_cents"] >= 0
    assert data["tier"] in ["BRONZE", "SILVER", "GOLD"]
    assert data["status"] == "ACTIVE"


def assert_coach(data: dict):
    _assert_common(data)
    assert data["discipline"] in ["SURF", "SKATE"]
    assert data["status"] == "ACTIVE"


def assert_rental_asset(data: dict):
    _assert_common(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["asset_tag"], str)
    assert data["condition"] in ["GOOD", "FAIR", "NEEDS_SERVICE"]
    assert data["status"] in ["AVAILABLE", "RESERVED", "OUT"]


def assert_lesson(data: dict):
    _assert_common(data)
    assert data["discipline"] in ["SURF", "SKATE"]
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"]


def assert_rental(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in ["RESERVED", "PICKED_UP", "RETURNED", "RELEASED"]
    assert data["payment_status"] in ["DEPOSIT_HELD", "DEPOSIT_CAPTURED", "DEPOSIT_REFUNDED"]
    assert isinstance(data["rental_fee_cents"], int) and data["rental_fee_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0


def assert_board_build(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "RESERVED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["provisional_cost_cents"], int) and data["provisional_cost_cents"] >= 0
    assert isinstance(data["final_cost_cents"], int) and data["final_cost_cents"] >= 0


def assert_service_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ["INTAKE", "READY", "PICKED_UP", "CANCELLED"]
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0


def assert_trade_in(data: dict):
    _assert_common(data)
    assert data["mode"] in ["TRADE_IN", "CONSIGNMENT"]
    assert data["status"] in ["RECEIVED", "APPRAISED", "ACCEPTED", "REJECTED", "LISTED", "SOLD"]


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "QUOTED", "CUSTOMER_REVIEW", "APPROVED", "FULFILLED", "CANCELLED",
    ]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_event(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "PUBLISHED", "CANCELLED"]
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0


def assert_event_entry(data: dict):
    _assert_common(data)
    assert data["role"] in ["TEAM_RIDER", "PUBLIC"]
    assert data["status"] in ["REGISTERED", "CANCELLED"]
    assert isinstance(data["points_awarded"], int) and data["points_awarded"] >= 0
