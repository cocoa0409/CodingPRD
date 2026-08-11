"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["date_of_birth"], str)
    assert data["skier_type"] in ("TYPE_1", "TYPE_2", "TYPE_3")
    assert data["standing"] in ("GOOD_STANDING", "WATCH", "BARRED")
    assert isinstance(data["late_return_count"], int) and data["late_return_count"] >= 0


def assert_equipment_item(data: dict):
    _assert_common_fields(data)
    assert data["gear_type"] in ("SKI", "SNOWBOARD", "BOOT", "POLES")
    assert data["tier"] in ("STANDARD", "PERFORMANCE", "DEMO", "JUNIOR")
    assert data["status"] in (
        "AVAILABLE", "RESERVED", "OUT", "AWAITING_INSPECTION",
        "IN_SERVICE", "RETIRED", "LOST", "SOLD",
    )
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["base_daily_rate_cents"], int)
    assert isinstance(data["accrued_rental_days"], int) and data["accrued_rental_days"] >= 0


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert data["fulfillment_status"] in (
        "DRAFT", "CONFIRMED", "ACTIVE", "OVERDUE", "RETURNED", "CLOSED", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED", "SETTLED", "VOIDED")
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["deposit_minimum_cents"], int)
    assert isinstance(data["deposit_authorized_cents"], int)
    assert isinstance(data["deposit_captured_cents"], int)
    assert isinstance(data["deposit_released_cents"], int)


def assert_reservation_item(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("QUEUED", "ASSIGNED", "RELEASED", "RETURNED")
    assert data["gear_type_requested"] in ("SKI", "SNOWBOARD", "BOOT", "POLES")
    assert data["tier_requested"] in ("STANDARD", "PERFORMANCE", "DEMO", "JUNIOR")


def assert_tune_ticket(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "INTAKE", "QUOTED", "APPROVED", "IN_PROGRESS",
        "QUALITY_CHECK", "READY", "PICKED_UP", "CANCELLED",
    )
    assert isinstance(data["services"], list) and len(data["services"]) > 0
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] > 0
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0


def assert_season_lease(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "SETTLED")
    assert data["package_tier"] in ("JUNIOR_SKI", "JUNIOR_BOARD")
    assert isinstance(data["swap_count"], int) and data["swap_count"] >= 0


def assert_demo_credit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "REDEEMED", "EXPIRED")
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] > 0
    assert isinstance(data["credit_cents"], int)


def assert_purchase_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "PAID", "FULFILLED", "CANCELLED")
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["amount_due_cents"], int)


def assert_damage_assessment(data: dict):
    _assert_common_fields(data)
    assert data["severity"] in ("COSMETIC", "MINOR", "MAJOR", "TOTAL_LOSS")
    assert data["status"] in ("DRAFT", "INVOICED", "DISPUTED", "PAID", "WAIVED")
    assert isinstance(data["charge_cents"], int)
    assert isinstance(data["deposit_captured_cents"], int)
    assert isinstance(data["remainder_due_cents"], int)


def assert_pickup_window(data: dict):
    _assert_common_fields(data)
    assert data["posture"] in ("OPEN", "FULL", "CLOSED")
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert isinstance(data["van_capacity"], int) and data["van_capacity"] > 0


def assert_pickup_booking(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_shop_day_capacity(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["base_labor_minutes"], int)
    assert isinstance(data["rush_reserved_minutes"], int)
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0
    assert isinstance(data["rush_booked_minutes"], int) and data["rush_booked_minutes"] >= 0


def assert_deposit_conservation(reservation: dict):
    """Deposit waterfall conservation law (PRD The Deposit Waterfall):
    once closed or cancelled, authorized == captured + released."""
    assert reservation["deposit_authorized_cents"] == (
        reservation["deposit_captured_cents"] + reservation["deposit_released_cents"]
    ), (
        "deposit conservation violated: "
        f"{reservation['deposit_authorized_cents']} != "
        f"{reservation['deposit_captured_cents']} + {reservation['deposit_released_cents']}"
    )
