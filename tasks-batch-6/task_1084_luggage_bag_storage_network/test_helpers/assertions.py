"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_host(data: dict):
    _common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for f in ("platform_fee_bps", "max_concurrent_bookings", "pending_payout_cents",
              "payout_balance_cents", "lifetime_earnings_cents", "rating_sum", "rating_count"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_traveler(data: dict):
    _common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] == "ACTIVE"


def assert_insurance_plan(data: dict):
    _common(data)
    assert data["tier"] in ("NONE", "BASIC", "PREMIUM")
    assert isinstance(data["per_bag_coverage_cents"], int)
    assert isinstance(data["premium_cents_per_bag_day"], int)


def assert_location(data: dict):
    _common(data)
    assert is_valid_uuid(data["host_id"])
    assert data["status"] in ("DRAFT", "OPEN", "SUSPENDED", "CLOSED")
    for f in ("daily_bag_capacity", "oversize_capacity", "per_bag_day_rate_cents",
              "oversize_surcharge_cents_per_day"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_booking(data: dict):
    _common(data)
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["traveler_id"])
    assert is_valid_uuid(data["insurance_plan_id"])
    assert data["status"] in ("RESERVED", "STORED", "OVERDUE", "COMPLETED", "CANCELLED")
    for f in ("bag_count", "oversize_count", "billable_days", "estimated_total_cents",
              "overage_days", "late_fee_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_bag(data: dict):
    _common(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["declared_value_cents"], int)
    assert isinstance(data["dimension_sum_cm"], int)
    assert isinstance(data["is_oversize"], bool)
    assert data["status"] in ("AWAITING_DROP", "SEALED", "RETRIEVED", "VOIDED")


def assert_extension(data: dict):
    _common(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["status"] in ("REQUESTED", "CONFIRMED", "REJECTED")
    assert isinstance(data["added_days"], int)


def assert_claim(data: dict):
    _common(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["bag_id"])
    assert data["reason"] in ("DAMAGE", "LOSS", "THEFT")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED")
    assert isinstance(data["claimed_amount_cents"], int)


def assert_payout(data: dict):
    _common(data)
    assert is_valid_uuid(data["host_id"])
    assert is_valid_uuid(data["booking_id"])
    assert data["status"] in ("PENDING", "RELEASED", "REVERSED")
    for f in ("gross_cents", "platform_fee_cents", "claim_deduction_cents", "net_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_rating(data: dict):
    _common(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["score"] in (1, 2, 3, 4, 5)


def assert_payout_partition(payout: dict):
    """net_cents = gross - platform_fee - claim_deduction (money partition invariant)."""
    assert payout["net_cents"] == (
        payout["gross_cents"] - payout["platform_fee_cents"] - payout["claim_deduction_cents"]
    ), "net_cents must equal gross - platform_fee - claim_deduction"
