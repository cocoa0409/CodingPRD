"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in [
        "DECK", "TRUCK", "WHEELS", "BEARINGS", "GRIP", "WAX", "SURFBOARD", "ACCESSORY"
    ]
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert data["stock_on_hand"] >= 0
    assert data["stock_reserved"] >= 0
    # stock_available is the derived figure = on_hand - reserved (PRD §2.7).
    assert data["stock_available"] == data["stock_on_hand"] - data["stock_reserved"], (
        f"stock_available {data['stock_available']} != on_hand {data['stock_on_hand']} "
        f"- reserved {data['stock_reserved']}"
    )


def assert_member(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert data["tier"] in ["STANDARD", "PRO", "TEAM"]
    assert data["points_balance"] >= 0
    assert data["lifetime_points"] >= 0
    assert data["store_credit_cents"] >= 0


def assert_board_build(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "COMPONENTS_RESERVED", "ASSEMBLED", "SETUP_COMPLETE", "COMPLETED", "CANCELLED"
    ]


def assert_service_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "DONE", "CANCELLED"]


def assert_rental(data: dict):
    _assert_common(data)
    assert data["status"] in ["RESERVED", "CHECKED_OUT", "RETURNED", "CANCELLED"]


def assert_lesson(data: dict):
    _assert_common(data)
    assert data["status"] in ["BOOKED", "CONFIRMED", "COMPLETED", "CANCELLED"]


def assert_trade_in(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "RECEIVED", "APPRAISED", "CASH_SETTLED", "LISTED", "SOLD", "RETURNED"
    ]


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "QUOTED", "DEPOSIT_PAID", "FULFILLED", "CANCELLED"]


def assert_event(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "CLOSED"]
    assert data["registration_count"] >= 0


def assert_event_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ["REGISTERED", "CANCELLED"]
