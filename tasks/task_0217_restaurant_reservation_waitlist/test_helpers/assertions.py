"""Entity assertions and domain invariant checkers.

Versioned entities carry the id / created_at / updated_at / version quadruple;
the two append-only entities (SpecialRequest, Notification) carry only id and
created_at and MUST NOT be asserted to have updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-field helpers ─────────────────────────────────────────────────
def _assert_versioned_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version begins at 1"


def _assert_appendonly_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not expose version"
    assert "updated_at" not in data, "append-only entity must not expose updated_at"


# ─── Versioned entities ───────────────────────────────────────────────────
def assert_restaurant(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["per_seat_deposit_cents"], int)
    assert isinstance(data["deposit_required_party_threshold"], int)


def assert_dining_area(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["restaurant_id"], str)
    assert data["kind"] in ("STANDARD", "PRIVATE")
    assert data["status"] in ("AVAILABLE", "BOUGHT_OUT")


def assert_table(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["dining_area_id"], str)
    assert isinstance(data["min_party_size"], int)
    assert isinstance(data["max_party_size"], int)
    assert data["max_party_size"] >= data["min_party_size"]
    assert data["status"] in ("AVAILABLE", "SEATED", "DIRTY", "OUT_OF_SERVICE")


def assert_service_period(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["restaurant_id"], str)
    assert data["slot_interval_minutes"] in (15, 30, 60)
    assert isinstance(data["pacing_max_covers_per_slot"], int)


def assert_customer(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["phone"], str)
    assert isinstance(data["no_show_strikes"], int)
    assert isinstance(data["lifetime_reservations"], int)
    assert isinstance(data["lifetime_failures"], int)
    assert isinstance(data["settled_reliability_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "BLOCKED")


def assert_reservation(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["restaurant_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["party_size"], int)
    assert is_iso8601_timestamp(data.get("reservation_start", ""))
    assert isinstance(data["deposit_required"], bool)
    assert isinstance(data["cancellation_fee_cents"], int)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "SEATED", "COMPLETED", "CANCELLED", "NO_SHOW"
    )


def assert_waitlist_entry(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["restaurant_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["party_size"], int)
    assert is_iso8601_timestamp(data.get("requested_start", ""))
    assert is_iso8601_timestamp(data.get("joined_at", ""))
    assert isinstance(data["notify_count"], int)
    assert data["status"] in (
        "WAITING", "NOTIFIED", "CONVERTED", "EXPIRED", "CANCELLED"
    )


def assert_deposit_hold(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["reservation_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["captured_cents"], int)
    assert data["captured_cents"] <= data["amount_cents"]
    assert data["status"] in ("HELD", "CAPTURED", "RELEASED", "EXPIRED")


def assert_private_dining_event(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["restaurant_id"], str)
    assert isinstance(data["dining_area_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["food_minimum_cents"], int)
    assert isinstance(data["deposit_due_cents"], int)
    assert data["status"] in (
        "INQUIRY", "PROPOSED", "CONFIRMED", "COMPLETED", "CANCELLED"
    )


# ─── Append-only entities ─────────────────────────────────────────────────
def assert_special_request(data: dict):
    _assert_appendonly_common(data)
    assert isinstance(data["reservation_id"], str)
    assert data["category"] in (
        "DIETARY", "SEATING", "OCCASION", "ACCESSIBILITY", "OTHER"
    )
    assert isinstance(data["note"], str)
    assert isinstance(data["acknowledged"], bool)


def assert_notification(data: dict):
    _assert_appendonly_common(data)
    assert data["subject_type"] in ("RESERVATION", "WAITLIST_ENTRY")
    assert isinstance(data["subject_id"], str)
    assert data["channel"] in ("SMS", "EMAIL")
    assert data["template"] in (
        "WAITLIST_TABLE_READY", "RESERVATION_CONFIRMED", "RESERVATION_REMINDER",
        "NO_SHOW_FEE_CHARGED", "RESERVATION_CANCELLED",
    )
