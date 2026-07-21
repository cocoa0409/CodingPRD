"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_table(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and data["label"]
    assert data["zone"] in ["MAIN", "QUIET", "PATIO"]
    assert data["seats"] >= 1
    assert data["half_hour_rate_cents"] >= 0
    assert data["day_pass_cents"] >= 0
    assert data["cover_fee_cents"] >= 0
    assert data["min_spend_cents"] >= 0
    assert data["status"] in ["AVAILABLE", "OUT_OF_SERVICE"]


def assert_membership(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str)
    assert data["tier"] in ["BRONZE", "SILVER", "GOLD"]
    assert data["points_balance"] >= 0, "points_balance never goes negative"
    assert data["lifetime_points"] >= 0
    assert data["no_show_strikes"] >= 0
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CANCELLED"]
    assert data["last_redemption_status"] in ["APPLIED", "REVERSED", "NONE"]


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ["BOOKED", "SEATED", "COMPLETED", "CANCELLED", "NO_SHOW"]
    assert data["party_size"] >= 1
    assert isinstance(data["deposit_forfeited"], bool)


def assert_fnb_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "VOID"]
    assert data["total_cents"] >= 0


def assert_game_copy(data: dict):
    _assert_common(data)
    assert data["condition"] in ["MINT", "GOOD", "WORN", "DAMAGED", "LOST"]
    assert data["status"] in ["AVAILABLE", "CHECKED_OUT", "RETIRED"]
    assert data["replacement_value_cents"] >= 0


def assert_checkout(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "RETURNED", "LOST"]
    assert data["condition_fee_cents"] >= 0


def assert_tournament(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "OPEN", "RUNNING", "COMPLETED", "CANCELLED"]
    assert data["format"] in ["SINGLE_ELIM", "LEAGUE", "CASUAL"]
    assert data["capacity"] >= 1


def assert_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ["REGISTERED", "CHECKED_IN", "WITHDRAWN", "REFUNDED"]
    assert data["refunded_cents"] >= 0


def assert_room(data: dict):
    _assert_common(data)
    assert data["capacity"] >= 1
    assert data["hourly_rate_cents"] >= 0
    assert data["status"] in ["AVAILABLE", "OUT_OF_SERVICE"]


def assert_private_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ["HELD", "CONFIRMED", "SUPERSEDED", "CANCELLED", "COMPLETED"]
    assert data["quoted_total_cents"] >= 0
    assert data["deposit_cents"] >= 0


def assert_retail_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_type"] in ["IN_STOCK", "PREORDER"]
    assert data["status"] in ["AWAITING_STOCK", "READY", "FULFILLED", "CANCELLED"]
    assert data["quantity"] >= 1
