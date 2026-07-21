"""Entity assertions and domain invariant checkers.

Each assert_<entity> validates the response structure against the PRD contract
using the framework's generic format checkers. Invariant checkers encode the
cross-field rules the PRD pins as always-true.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["state_code"] in ["CA", "OR", "NY"]
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_sku(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ["COOKWARE", "KNIVES", "COFFEE", "APPLIANCE", "TABLETOP"]
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["available_qty"], int) and data["available_qty"] >= 0
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]
    assert_sku_inventory_invariant(data)


def assert_sku_inventory_invariant(data: dict):
    """available_qty + reserved_qty == on_hand_qty, available never negative (PRD §2.8)."""
    assert data["available_qty"] >= 0, "available_qty must never be negative"
    assert data["available_qty"] + data["reserved_qty"] == data["on_hand_qty"], (
        "invariant available_qty + reserved_qty == on_hand_qty violated: "
        f"{data['available_qty']} + {data['reserved_qty']} != {data['on_hand_qty']}"
    )


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["tier"] in ["STANDARD", "SILVER", "GOLD"]
    assert isinstance(data["annual_spend_cents"], int) and data["annual_spend_cents"] >= 0
    assert isinstance(data["pending_points"], int)
    assert isinstance(data["earned_points"], int)
    assert isinstance(data["wallet_credit_cents"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]
    assert data["fulfillment_status"] in ["RESERVED", "FULFILLED", "CANCELED"]
    assert data["tier_at_pricing"] in ["STANDARD", "SILVER", "GOLD"]
    assert data["fulfillment_type"] in ["BOPIS", "SHIP_FROM_STORE", "IN_STORE"]
    for field in ["subtotal_cents", "tier_discount_cents", "tax_cents", "total_cents",
                  "pending_points", "earned_points", "refunded_cents"]:
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert is_valid_uuid(line["line_id"]) or isinstance(line["line_id"], str)
        assert line["line_status"] in ["RESERVED", "FULFILLED", "VOID", "RETURNED"]


def assert_cooking_class(data: dict):
    _assert_common(data)
    assert data["station"] in ["DEMO_KITCHEN", "HEARTH_BAR"]
    assert data["status"] in ["DRAFT", "OPEN", "COMPLETED", "CANCELED"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["registered_count"], int) and data["registered_count"] >= 0


def assert_class_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ["BOOKED", "ATTENDED", "NO_SHOW", "CANCELED"]
    assert isinstance(data["seat_price_cents"], int)


def assert_service_ticket(data: dict):
    _assert_common(data)
    assert data["service_type"] in ["KNIFE_SHARPENING", "COFFEE_SERVICE"]
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELED"]


def assert_return(data: dict):
    _assert_common(data)
    assert data["reason"] in ["DEFECTIVE", "UNWANTED", "WRONG_ITEM"]
    assert data["refund_destination"] in ["ORIGINAL", "WALLET"]
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED"]


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "QUOTED", "REVISION_REQUESTED", "ACCEPTED", "CANCELED"]
    assert isinstance(data["quote_revision"], int) and data["quote_revision"] >= 0


def assert_registry(data: dict):
    _assert_common(data)
    assert data["event_type"] in ["WEDDING", "HOUSEWARMING", "BIRTHDAY"]
    assert data["status"] == "ACTIVE"
    assert isinstance(data["items"], list)
