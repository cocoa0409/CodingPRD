"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be int"
        assert data["version"] >= 1, "version starts at 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["loyalty_points_balance"], int)
    assert isinstance(data["lifetime_points_earned"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("TACKLE", "ROD", "REEL", "LINE", "LIVE_BAIT", "MISC")
    assert data["unit_price_cents"] >= 0
    assert data["stock_qty"] >= 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_license_type(data: dict):
    # LicenseType is config: id + created_at only, no version / updated_at.
    _assert_common(data, versioned=False)
    assert "version" not in data, "LicenseType carries no version"
    assert "updated_at" not in data, "LicenseType carries no updated_at"
    assert data["license_class"] in ("RESIDENT", "NONRESIDENT")
    assert data["base_price_cents"] >= 0
    assert data["validity_days"] > 0


def assert_license_sale(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "VOIDED")
    assert isinstance(data["price_paid_cents"], int)
    assert isinstance(data["points_earned"], int)
    assert isinstance(data["valid_from"], str) and data["valid_from"]
    assert isinstance(data["valid_until"], str) and data["valid_until"]


def assert_guide(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "SUSPENDED")


def assert_charter(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "FULL", "CANCELLED")
    assert data["capacity"] > 0
    assert data["booked_seats"] >= 0
    assert data["price_per_seat_cents"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["booking_status"] in (
        "RESERVED", "WAITLISTED", "CHECKED_IN", "COMPLETED", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["seats"] > 0
    assert isinstance(data["provisional_total_cents"], int)


def assert_tournament(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "OPEN", "IN_PROGRESS", "FINALIZED", "CANCELLED",
    )
    assert data["min_qualifying_weight_grams"] >= 0


def assert_entry(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REGISTERED", "CHECKED_IN", "WEIGHED", "WINNER", "WITHDRAWN",
    )
    assert isinstance(data["weigh_ins"], list)
    assert isinstance(data["best_weight_grams"], int)


def assert_service_order(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("REEL_REPAIR", "ROD_REPAIR", "SPOOLING")
    assert data["status"] in (
        "INTAKE", "DIAGNOSED", "IN_PROGRESS", "READY", "PICKED_UP", "CANCELLED",
    )
    assert data["base_service_cents"] >= 0
