"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_venue(data: dict):
    _versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["bay_count"], int) and data["bay_count"] >= 1
    assert isinstance(data["open_queue_length"], int) and data["open_queue_length"] >= 0
    assert isinstance(data["available_bay_count"], int)


def assert_bay(data: dict):
    _versioned(data)
    assert is_valid_uuid(data["venue_id"])
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE")
    assert isinstance(data["floor_level"], int) and data["floor_level"] >= 1


def assert_member(data: dict):
    _versioned(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["tier"] in ("STANDARD", "GOLD", "PLATINUM")
    assert isinstance(data["wallet_balance_cents"], int) and data["wallet_balance_cents"] >= 0
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert isinstance(data["pending_loyalty_points"], int) and data["pending_loyalty_points"] >= 0


def assert_game_card(data: dict):
    _versioned(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["credits_total"], int) and data["credits_total"] >= 1
    assert isinstance(data["credits_remaining"], int) and data["credits_remaining"] >= 0
    assert data["status"] in ("ACTIVE", "DEPLETED")


def assert_gift_card(data: dict):
    """GiftCard is immutable: carries id + created_at only — NO updated_at, NO version."""
    _common(data)
    assert "version" not in data, "GiftCard has no version field"
    assert "updated_at" not in data, "GiftCard has no updated_at field"
    assert isinstance(data["face_value_cents"], int) and data["face_value_cents"] >= 1
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0
    assert isinstance(data["redeemed_total_cents"], int) and data["redeemed_total_cents"] >= 0
    assert data["status"] in ("ISSUED", "DEPLETED")
    # Conservation invariant.
    assert data["remaining_cents"] + data["redeemed_total_cents"] == data["face_value_cents"], \
        "remaining_cents + redeemed_total_cents must equal face_value_cents"


def assert_reservation(data: dict):
    _versioned(data)
    assert data["status"] in ("HOLD", "CONFIRMED", "EXPIRED", "CANCELLED", "NO_SHOW")
    assert data["time_band"] in ("TWILIGHT", "OFFPEAK", "PEAK")
    assert data["day_type"] in ("WEEKDAY", "WEEKEND")
    assert data["pay_source"] in ("WALLET", "CARD_ON_FILE")
    assert isinstance(data["quoted_price_cents"], int) and data["quoted_price_cents"] >= 0
    assert isinstance(data["no_show_fee_cents"], int) and data["no_show_fee_cents"] >= 0


def assert_game_session(data: dict):
    _versioned(data)
    assert is_valid_uuid(data["bay_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["play_status"] in ("OPEN", "ENDED")
    assert data["billing_status"] in ("UNBILLED", "CHARGED", "VOID")
    assert isinstance(data["total_score"], int)
    assert isinstance(data["shot_count"], int) and data["shot_count"] >= 0
    assert isinstance(data["shots"], list)


def assert_event_package(data: dict):
    _versioned(data)
    assert data["status"] in ("QUOTED", "NEGOTIATING", "CONFIRMED", "SETTLED", "CANCELLED")
    assert isinstance(data["headcount_estimate"], int) and data["headcount_estimate"] >= 1
    assert isinstance(data["per_head_package_cents"], int) and data["per_head_package_cents"] >= 0
    assert isinstance(data["estimated_total_cents"], int)


def assert_fb_tab(data: dict):
    _versioned(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["line_items"], list)
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["gratuity_cents"], int) and data["gratuity_cents"] >= 0
    assert isinstance(data["tax_cents"], int) and data["tax_cents"] >= 0
    assert data["total_cents"] == data["subtotal_cents"] + data["gratuity_cents"] + data["tax_cents"], \
        "total_cents must equal subtotal + gratuity + tax"


def assert_queue_ticket(data: dict):
    _versioned(data)
    assert is_valid_uuid(data["venue_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in ("WAITING", "SEATED", "CANCELLED", "EXPIRED")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1


def assert_lesson(data: dict):
    _versioned(data)
    assert data["kind"] in ("PRIVATE_LESSON", "GROUP_CLINIC", "SIMULATOR")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["seats"], int) and data["seats"] >= 1


def assert_charge(data: dict):
    """Charge is immutable: carries id + created_at only — NO updated_at, NO version."""
    _common(data)
    assert "version" not in data, "Charge has no version field"
    assert "updated_at" not in data, "Charge has no updated_at field"
    assert data["kind"] in (
        "BAY_RESERVATION", "SESSION_SETTLEMENT", "EVENT_SETTLEMENT", "NO_SHOW_FEE")
    assert data["status"] in ("SETTLED", "REVERSED")
    assert data["pay_source"] in ("WALLET", "CARD_ON_FILE")
    assert isinstance(data["amount_cents"], int)
