"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract.
Generic format checks come from the framework.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-field helpers ─────────────────────────────
def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without milliseconds) into a tz-aware datetime."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC timestamp: {value!r}"
    s = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_same_instant(actual: str, expected_iso: str):
    """Assert two ISO 8601 strings denote the same UTC instant (serialization-agnostic)."""
    assert parse_iso8601(actual) == parse_iso8601(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


# ─── Entity assertions ────────────────────────────────
def assert_venue(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)
    assert isinstance(data["open_minute_of_day"], int)
    assert isinstance(data["close_minute_of_day"], int)
    assert 0 <= data["open_minute_of_day"] < data["close_minute_of_day"] <= 1440
    assert isinstance(data["no_show_fee_pct"], (int, float))
    assert 0.0 <= data["no_show_fee_pct"] <= 1.0
    assert isinstance(data["no_show_strike_limit"], int) and data["no_show_strike_limit"] >= 1


def assert_room(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["min_group_size"], int) and data["min_group_size"] >= 1
    assert isinstance(data["max_group_size"], int) and data["max_group_size"] >= data["min_group_size"]
    assert isinstance(data["min_age"], int) and data["min_age"] >= 0
    assert isinstance(data["waiver_required"], bool)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["private_surcharge_cents"], int) and data["private_surcharge_cents"] >= 0
    assert isinstance(data["game_minutes"], int) and data["game_minutes"] >= 1
    assert isinstance(data["reset_buffer_minutes"], int) and data["reset_buffer_minutes"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_pricing_rule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a UUID"
    assert isinstance(data["peak_dow_mask"], int) and 0 <= data["peak_dow_mask"] <= 127
    assert isinstance(data["peak_start_minute_of_day"], int)
    assert isinstance(data["peak_end_minute_of_day"], int)
    assert isinstance(data["peak_multiplier_bps"], int) and data["peak_multiplier_bps"] >= 10000
    assert isinstance(data["large_group_threshold"], int) and data["large_group_threshold"] >= 1
    assert isinstance(data["large_group_multiplier_bps"], int) and data["large_group_multiplier_bps"] >= 10000


def assert_game_master(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("AVAILABLE", "OFF_DUTY")
    assert isinstance(data["active_assignment_count"], int) and data["active_assignment_count"] >= 0


def assert_time_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a UUID"
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert is_iso8601_timestamp(data["start_utc"]), "start_utc must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data["game_end_utc"]), "game_end_utc must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data["block_end_utc"]), "block_end_utc must be ISO 8601 UTC"
    assert data["status"] in ("OPEN", "HELD", "BOOKED", "BLOCKED", "CLOSED")


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["no_show_strike_count"], int) and data["no_show_strike_count"] >= 0


def assert_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a UUID"
    assert is_valid_uuid(data.get("time_slot_id", "")), "time_slot_id must be a UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["group_size"], int) and data["group_size"] >= 1
    assert isinstance(data["is_private"], bool)
    assert data["lifecycle_status"] in (
        "DRAFT", "CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED", "REFUNDED")


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["age"], int) and data["age"] >= 0
    assert data["waiver_status"] in ("PENDING", "SIGNED", "REVOKED")
    assert isinstance(data["checked_in"], bool)


def assert_gift_card(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["initial_balance_cents"], int) and data["initial_balance_cents"] >= 1
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert data["status"] in ("ACTIVE", "DEPLETED", "VOID")


def assert_gift_card_entry(data: dict):
    """Append-only ledger entry: id + created_at only (PRD Section 2.4) — no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_valid_uuid(data.get("gift_card_id", "")), "gift_card_id must be a UUID"
    assert data["entry_type"] in ("SPEND", "REFUND", "TOPUP")
    assert isinstance(data["delta_cents"], int)


# ─── Domain invariant checkers ────────────────────────
def assert_gift_card_balance_invariant(card: dict, initial_balance_cents: int, sum_deltas: int):
    """balance_cents == initial_balance_cents + sum(entry deltas) (PRD Section 2.6 / 3.9)."""
    assert card["balance_cents"] == initial_balance_cents + sum_deltas, (
        f"GiftCard.balance_cents should be {initial_balance_cents + sum_deltas}, "
        f"got {card['balance_cents']}"
    )
    assert card["balance_cents"] >= 0, "balance_cents must never be negative"
