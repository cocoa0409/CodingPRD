"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Assertions only check fields
the PRD guarantees on the response.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert 0.0 <= data["table_discount_pct"] <= 0.5


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["membership_status"] in ("ACTIVE", "EXPIRED", "SUSPENDED")
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_table(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "MAINTENANCE", "RETIRED")
    assert data["table_type"] in ("POOL_7FT", "POOL_9FT", "SNOOKER", "BILLIARDS")
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW",
    )
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1


def assert_session(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED", "VOIDED")
    assert isinstance(data["provisional_charge_cents"], int)
    assert isinstance(data["final_charge_cents"], int)


def assert_fnb_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "SUBMITTED", "VOIDED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_tournament(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "REGISTRATION_OPEN", "SEEDED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["open_slots"], int)
    assert isinstance(data["prize_pool_cents"], int) and data["prize_pool_cents"] >= 0


def assert_tournament_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENTERED", "CHECKED_IN", "WITHDRAWN", "ELIMINATED")


def assert_product(data: dict):
    _assert_common(data)
    assert data["category"] in ("CUE", "CASE", "ACCESSORY", "TABLE", "PART")
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0


def assert_repair_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "IN_PROGRESS", "READY", "PICKED_UP", "CANCELLED")
    assert data["service_type"] in ("CUE_RETIP", "CUE_REPAIR", "TABLE_RECOVER")


def assert_event(data: dict):
    _assert_common(data)
    assert data["booking_status"] in (
        "INQUIRY", "QUOTED", "BOOKED", "CONFIRMED", "COMPLETED", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED")
