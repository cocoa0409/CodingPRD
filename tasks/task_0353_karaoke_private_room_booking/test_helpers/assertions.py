"""Entity assertions and domain invariant checkers for the Karaoke Booking API.

Each assert_{entity}() validates the system-managed identity/timestamp fields and
the entity's declared field shapes. Song and Payment are immutable, so their
assertions deliberately forbid updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common quartet (id/created_at/updated_at/version) ─────────────
def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_immutable_fields(data: dict):
    """For Song and Payment: id + created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "version" not in data, "immutable entity must not carry a version field"
    assert "updated_at" not in data, "immutable entity must not carry an updated_at field"


def assert_venue(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str) and len(data["timezone"]) > 0
    assert 0 <= data["peak_start_minute"] <= 1439
    assert data["peak_start_minute"] < data["peak_end_minute"] <= 1439
    assert float(data["peak_multiplier"]) >= 1.0
    assert 0 < float(data["deposit_pct"]) <= 1
    assert data["cancellation_cutoff_hours"] >= 0
    assert data["grace_minutes"] >= 0
    assert data["overage_grace_minutes"] >= 0


def assert_room_type(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["venue_id"])
    assert data["name"] in ("SMALL", "MEDIUM", "LARGE", "VIP")
    assert data["capacity"] >= 1
    assert data["base_hourly_rate_cents"] >= 0
    assert data["fb_minimum_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_room(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["venue_id"])
    assert is_valid_uuid(data["room_type_id"])
    assert isinstance(data["label"], str)
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE")


def assert_group_package(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["name"], str)
    assert data["flat_price_cents"] >= 0
    assert float(data["included_hours"]) > 0
    assert is_valid_uuid(data["included_room_type_id"])
    assert data["included_fb_credit_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["venue_id"])
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["room_type_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["party_size"] >= 1
    assert is_iso8601_timestamp(data["slot_start_utc"])
    assert is_iso8601_timestamp(data["slot_end_utc"])
    assert data["status"] in (
        "HELD", "CONFIRMED", "CHECKED_IN", "CLOSED", "CANCELLED", "EXPIRED", "NO_SHOW",
    )


def assert_extension(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_iso8601_timestamp(data["new_slot_end_utc"])
    assert isinstance(data["added_minutes"], int)
    assert data["status"] == "APPLIED"


def assert_queue_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["song_id"])
    assert isinstance(data["priority"], int)
    assert data["status"] in ("PENDING", "PLAYED", "SKIPPED", "CANCELLED")


def assert_fb_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert isinstance(data["description"], str)
    assert data["unit_price_cents"] >= 0
    assert data["quantity"] >= 1
    assert data["line_total_cents"] == data["unit_price_cents"] * data["quantity"]
    assert data["status"] in ("PLACED", "VOID")


def assert_song(data: dict):
    _assert_immutable_fields(data)
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["artist"], str)
    assert data["duration_seconds"] >= 1
    assert data["language"] in ("EN", "JP", "KR", "ZH", "ES", "OTHER")


def assert_payment(data: dict):
    _assert_immutable_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert data["kind"] in ("DEPOSIT", "SETTLEMENT", "REFUND", "FORFEIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


# ─── Payment-ledger helpers ───────────────────────────────────────
def payments_of_kind(payments: list, kind: str) -> list:
    """Filter a payment list to a single kind (DEPOSIT/SETTLEMENT/REFUND/FORFEIT)."""
    return [p for p in payments if p.get("kind") == kind]


def sum_amount_for_kind(payments: list, kind: str) -> int:
    """Sum amount_cents over payments of a given kind."""
    return sum(p["amount_cents"] for p in payments_of_kind(payments, kind))
