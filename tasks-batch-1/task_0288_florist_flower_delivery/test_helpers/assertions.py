"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system fields for resources with id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version is an int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["loyalty_tier"] in ("STANDARD", "SILVER", "GOLD")
    assert isinstance(data["lifetime_delivered_count"], int) and data["lifetime_delivered_count"] >= 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_code"], str) and len(data["zone_code"]) > 0
    assert isinstance(data["base_delivery_fee_cents"], int) and data["base_delivery_fee_cents"] >= 0
    assert 0 <= data["same_day_cutoff_hour_utc"] <= 23
    assert data["window_capacity_per_slot"] >= 1
    assert isinstance(data["active"], bool)


def assert_arrangement(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert data["premium_tier"] in ("STANDARD", "PREMIUM")
    assert data["substitution_policy"] in ("NONE", "SAME_VALUE", "FLORIST_CHOICE")
    assert 0 <= data["substitution_cap_pct"] <= 1
    assert isinstance(data["active"], bool)


def assert_holiday_window(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["surge_multiplier"] > 1.0
    assert isinstance(data["applies_to_standard"], bool)
    assert 0 <= data["surge_cutoff_hour_utc"] <= 23


def assert_florist(data: dict):
    _assert_common(data)
    assert isinstance(data["shop_name"], str)
    assert is_valid_uuid(data.get("covered_zone_id", "")), "covered_zone_id must be a UUID"
    assert data["daily_capacity"] >= 1
    assert 0.0 <= data["quality_rating"] <= 5.0
    assert isinstance(data["wire_surcharge_cents"], int) and data["wire_surcharge_cents"] >= 0
    assert isinstance(data["accepting"], bool)


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("arrangement_id", ""))
    assert is_valid_uuid(data.get("zone_id", ""))
    assert data["occasion"] in ("GENERAL", "BIRTHDAY", "ANNIVERSARY", "SYMPATHY", "ROMANCE")
    assert isinstance(data["card_message"], str) and len(data["card_message"]) <= 240
    assert data["window_start_minute"] < data["window_end_minute"]
    assert data["fulfillment_status"] in (
        "DRAFT", "QUOTED", "BOOKED", "IN_TRANSIT", "DELIVERED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED", "REFUNDED")
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)
    assert isinstance(data["wallet_credit_applied_cents"], int)
    assert isinstance(data["is_same_day"], bool)


def assert_wire_fulfillment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("florist_id", ""))
    assert data["status"] in ("ASSIGNED", "ACCEPTED", "RELEASED")
    assert isinstance(data["florist_surcharge_cents"], int) and data["florist_surcharge_cents"] >= 0


def assert_substitution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("florist_id", ""))
    assert isinstance(data["price_delta_cents"], int)
    assert isinstance(data["accepted"], bool)


def assert_quality_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["reason"] in ("WILTED", "WRONG_ITEM", "LATE", "DAMAGED")
    assert data["requested_remedy"] in ("REDELIVERY", "REFUND")
    assert data["status"] in ("OPEN", "APPROVED", "REJECTED", "RESOLVED")
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0


def assert_recurring_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["cadence"] in ("WEEKLY", "MONTHLY")
    assert data["occurrences_remaining"] >= 0
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert 0 <= data["recurring_discount_pct"] <= 0.5


def assert_delivery_slot(data: dict):
    """DeliverySlot carries only id + created_at (PRD §2.4); no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DeliverySlot must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "DeliverySlot must not carry version (PRD §2.4)"
    assert isinstance(data["released"], bool)
