"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lean_fields(data: dict):
    """Lean entities carry only id + created_at; no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lean entity must NOT carry updated_at"
    assert "version" not in data, "lean entity must NOT carry version"


def assert_park(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_gate_capacity"], int) and data["total_gate_capacity"] >= 1
    assert data["weather_status"] in ("CLEAR", "STORM_WATCH", "RAINED_OUT")
    assert isinstance(data["open_window_count"], int) and data["open_window_count"] >= 0
    assert isinstance(data["resident_zip_prefixes"], list)
    assert isinstance(data["rain_check_value_cents"], int) and data["rain_check_value_cents"] >= 0


def assert_pricing_policy(data: dict):
    _assert_common_fields(data)
    assert data["product_type"] in ("DAY_TICKET", "SEASON_PASS")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_entry_window(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "RESTRICTED", "CLOSED", "RAINED_OUT")
    assert isinstance(data["window_capacity"], int) and data["window_capacity"] >= 1
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["admitted_count"], int) and data["admitted_count"] >= 0


def assert_cabana(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in ("STANDARD", "PREMIUM", "CABANA_SUITE")
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert isinstance(data["turnover_buffer_minutes"], int) and data["turnover_buffer_minutes"] >= 0


def assert_locker(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_guest(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["height_cm"], int) and data["height_cm"] >= 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_order(data: dict):
    _assert_common_fields(data)
    assert data["product_type"] in ("DAY_TICKET", "SEASON_PASS")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["payment_status"] in ("PENDING", "PAID", "VOID", "REFUNDED")
    assert data["fulfillment_status"] in ("UNFULFILLED", "FULFILLED", "CANCELLED")
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["wallet_credit_used_cents"], int) and data["wallet_credit_used_cents"] >= 0


def assert_admission(data: dict):
    _assert_common_fields(data)
    assert data["product_type"] in ("DAY_TICKET", "SEASON_PASS")
    assert data["status"] in (
        "ISSUED", "CONFIRMED", "CHECKED_IN", "FROZEN", "RAINED_OUT", "CANCELLED"
    )
    assert isinstance(data["ticket_price_cents"], int) and data["ticket_price_cents"] >= 0
    assert isinstance(data["freeze_days_used"], int) and data["freeze_days_used"] >= 0
    if data.get("band_color") is not None:
        assert data["band_color"] in ("GREEN", "YELLOW", "RED")


def assert_cabana_rental(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("HELD", "CONFIRMED", "CANCELLED", "RAINED_OUT")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0


def assert_locker_rental(data: dict):
    """LockerRental is lean: id + created_at only (PRD §2.4)."""
    _assert_lean_fields(data)
    assert isinstance(data["hours_billed"], int) and data["hours_billed"] >= 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0


def assert_rain_check(data: dict):
    _assert_common_fields(data)
    assert data["source_kind"] in ("ADMISSION", "CABANA_RENTAL")
    assert data["status"] in ("ISSUED", "SETTLED", "EXPIRED")
    assert isinstance(data["value_cents"], int) and data["value_cents"] >= 0


def assert_window_capacity_invariant(data: dict):
    """reserved_count + admitted_count never exceeds window_capacity (PRD §3.4)."""
    assert data["reserved_count"] + data["admitted_count"] <= data["window_capacity"], (
        f"reserved_count {data['reserved_count']} + admitted_count "
        f"{data['admitted_count']} exceeds window_capacity {data['window_capacity']}"
    )
