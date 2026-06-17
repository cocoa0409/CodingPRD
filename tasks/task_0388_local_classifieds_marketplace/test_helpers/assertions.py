"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the field shape the PRD promises for that entity.
Lightweight records (Category, Message, SafeTradeSpot, Alert) carry only
id + created_at and are validated as such.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "member id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["display_name"], str)
    assert data["role_kind"] in ("SELLER", "BUYER", "BOTH")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "BANNED")
    assert isinstance(data["phone_verified"], bool)
    assert isinstance(data["trust_score"], int)
    assert 0 <= data["trust_score"] <= 100, "trust_score clamped to [0,100]"
    assert isinstance(data["upheld_flag_count"], int) and data["upheld_flag_count"] >= 0
    assert isinstance(data["active_listing_count"], int) and data["active_listing_count"] >= 0
    assert isinstance(data["version"], int)


def assert_listing(data: dict, expect_floor: bool = False):
    assert is_valid_uuid(data.get("id", "")), "listing id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["category_slug"], str)
    assert isinstance(data["title"], str) and 0 < len(data["title"]) <= 120
    assert isinstance(data["ask_price_cents"], int) and data["ask_price_cents"] >= 1
    assert data["publication_status"] in ("DRAFT", "ACTIVE", "EXPIRED", "REMOVED")
    assert data["sale_status"] in ("AVAILABLE", "RESERVED", "SOLD")
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    assert isinstance(data["open_offer_count"], int) and data["open_offer_count"] >= 0
    assert isinstance(data["active_flag_count"], int) and data["active_flag_count"] >= 0
    assert isinstance(data["version"], int)
    if expect_floor:
        assert isinstance(data["min_acceptable_price_cents"], int)
        assert data["min_acceptable_price_cents"] >= 1
        assert data["min_acceptable_price_cents"] <= data["ask_price_cents"]


def assert_conversation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "conversation id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["listing_id"], str)
    assert isinstance(data["buyer_id"], str)
    assert isinstance(data["seller_id"], str)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["message_count"], int) and data["message_count"] >= 0
    assert isinstance(data["version"], int)


def assert_message(data: dict):
    assert is_valid_uuid(data.get("id", "")), "message id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["conversation_id"], str)
    assert isinstance(data["sender_id"], str)
    assert isinstance(data["body"], str) and 0 < len(data["body"]) <= 2000
    # Append-only record: no version field.
    assert "version" not in data, "Message is append-only and carries no version"


def assert_offer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "offer id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["conversation_id"], str)
    assert isinstance(data["listing_id"], str)
    assert isinstance(data["buyer_id"], str)
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["last_actor_side"] in ("BUYER", "SELLER")
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert data["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["version"], int)


def assert_safe_trade_spot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "spot id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["name"], str)
    assert isinstance(data["is_police_verified"], bool)
    assert isinstance(data["open_minute_of_day"], int)
    assert isinstance(data["close_minute_of_day"], int)
    assert 0 <= data["open_minute_of_day"] < data["close_minute_of_day"] <= 1440


def assert_meetup(data: dict):
    assert is_valid_uuid(data.get("id", "")), "meetup id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["offer_id"], str)
    assert isinstance(data["listing_id"], str)
    assert isinstance(data["spot_id"], str)
    assert isinstance(data["buyer_id"], str)
    assert isinstance(data["seller_id"], str)
    assert data["status"] in ("PROPOSED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["version"], int)


def assert_flag(data: dict):
    assert is_valid_uuid(data.get("id", "")), "flag id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["reporter_id"], str)
    assert data["target_type"] in ("LISTING", "MEMBER")
    assert data["reason"] in ("SPAM", "PROHIBITED", "SCAM", "MISCATEGORIZED", "OTHER")
    assert data["status"] in ("OPEN", "UPHELD", "DISMISSED")
    assert isinstance(data["version"], int)


def assert_saved_search(data: dict):
    assert is_valid_uuid(data.get("id", "")), "saved search id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["owner_id"], str)
    assert isinstance(data["category_slug"], str)
    assert isinstance(data["max_price_cents"], int) and data["max_price_cents"] >= 0
    assert isinstance(data["alert_count"], int) and data["alert_count"] >= 0
    assert isinstance(data["version"], int)


def assert_alert(data: dict):
    assert is_valid_uuid(data.get("id", "")), "alert id must be valid UUID"
    assert isinstance(data["saved_search_id"], str)
    assert isinstance(data["listing_id"], str)
    # Append-only record: no version field.
    assert "version" not in data, "Alert is append-only and carries no version"


def assert_category(data: dict):
    assert is_valid_uuid(data.get("id", "")), "category id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["slug"], str)
    assert isinstance(data["name"], str)
    # Immutable configuration record: no version field.
    assert "version" not in data, "Category is immutable and carries no version"
