"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_venue(data: dict):
    assert is_valid_uuid(data.get("id", "")), "venue id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str)
    assert data["weather_status"] in ["CLEAR", "ADVISORY", "SEVERE"]
    assert data["operational_state"] in ["OPEN", "RESTRICTED", "SHUTDOWN"]
    assert isinstance(data["open_attraction_count"], int)
    assert data["open_attraction_count"] >= 0
    assert isinstance(data["version"], int)


def assert_attraction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "attraction id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str)
    assert isinstance(data["min_age"], int) and data["min_age"] >= 0
    assert isinstance(data["scare_level"], int) and 1 <= data["scare_level"] <= 5
    assert isinstance(data["throughput_per_slot"], int) and data["throughput_per_slot"] >= 1
    assert data["status"] in ["OPEN", "PAUSED", "CLOSED"]
    assert isinstance(data["requires_waiver"], bool)
    assert isinstance(data["version"], int)


def assert_time_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "time_slot id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["admitted_count"], int) and data["admitted_count"] >= 0
    assert data["status"] in ["SCHEDULED", "CLOSED"]
    assert isinstance(data["version"], int)


def assert_pricing_rule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "pricing_rule id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in ["GA", "FAST_PASS", "VIP"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0


def assert_guest(data: dict):
    assert is_valid_uuid(data.get("id", "")), "guest id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["age"], int) and data["age"] >= 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["version"], int)


def assert_waiver(data: dict):
    assert is_valid_uuid(data.get("id", "")), "waiver id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["max_scare_level"], int) and 1 <= data["max_scare_level"] <= 5
    assert data["status"] in ["SIGNED", "EXPIRED", "REVOKED"]
    assert isinstance(data["version"], int)


def assert_reservation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "reservation id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_status"] in [
        "HELD", "RESERVED", "ADMITTED", "NO_SHOW", "CANCELLED"
    ]
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]
    assert isinstance(data["party_size"], int) and data["party_size"] >= 0
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["version"], int)


def assert_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ticket id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in ["GA", "FAST_PASS", "VIP"]
    assert isinstance(data["guest_age"], int) and data["guest_age"] >= 0
    assert isinstance(data["max_scare_level"], int)
    assert isinstance(data["version"], int)


def assert_pass(data: dict):
    assert is_valid_uuid(data.get("id", "")), "pass id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["redemptions_used"], int) and data["redemptions_used"] >= 0
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "CANCELLED"]
    assert isinstance(data["version"], int)


def assert_pass_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "pass_product id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ["SEASON", "GROUP"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["discount_pct"], int) and 0 <= data["discount_pct"] <= 100
    assert isinstance(data["min_party"], int) and data["min_party"] >= 1
    assert isinstance(data["max_redemptions"], int) and data["max_redemptions"] >= 1


def assert_scare_zone(data: dict):
    assert is_valid_uuid(data.get("id", "")), "scare_zone id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["min_actors"], int) and data["min_actors"] >= 1
    assert isinstance(data["checked_in_count"], int) and data["checked_in_count"] >= 0
    assert data["staffing_status"] in ["UNDERSTAFFED", "STAFFED"]
    assert isinstance(data["version"], int)


def assert_actor_shift(data: dict):
    assert is_valid_uuid(data.get("id", "")), "actor_shift id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["SCHEDULED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"]
    assert isinstance(data["version"], int)


def assert_closure(data: dict):
    assert is_valid_uuid(data.get("id", "")), "closure id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["reason"] in ["WEATHER", "SAFETY", "UNDERSTAFFED"]
    assert data["status"] in ["ACTIVE", "LIFTED"]
    assert isinstance(data["opened_reservation_refunds"], int)
    assert isinstance(data["version"], int)
