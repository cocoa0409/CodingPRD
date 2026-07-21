"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    _assert_common(data)
    assert data["membership_tier"] in ("BASIC", "PREMIER")
    assert data["membership_status"] in ("ACTIVE", "LAPSED")
    assert data["store_credit_cents"] >= 0, "store_credit_cents must never be negative"
    assert data["loyalty_points_balance"] >= 0, "loyalty_points_balance must never be negative"
    assert isinstance(data["lifetime_eligible_spend_cents"], int)


def assert_gear_sku(data: dict):
    _assert_common(data)
    assert data["category"] in ("TENT", "BACKPACK", "KAYAK", "STOVE", "APPAREL")
    assert data["retail_price_cents"] >= 0
    assert isinstance(data["rentable"], bool)
    assert data["daily_rental_rate_cents"] >= 0


def assert_gear_unit(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "RENTED_OUT")
    assert data["condition_grade"] in ("NEW", "GOOD", "FAIR")


def assert_rental(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "PICKED_UP", "RETURNED", "CANCELLED")
    assert data["rental_days"] >= 1, "rental_days has a floor of one day"
    assert data["estimated_charge_cents"] >= 0


def assert_sales_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("UNFULFILLED", "FULFILLED", "RETURNED")
    assert data["subtotal_cents"] >= 0
    assert data["total_cents"] >= 0


def assert_trade_in(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "OFFERED", "COUNTERED", "ACCEPTED", "LISTED", "SOLD", "REJECTED")
    assert data["payout_method"] in ("INSTANT_CREDIT", "CONSIGNMENT")


def assert_class_trip(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CANCELLED", "COMPLETED")
    assert data["seats_available"] >= 0, "seats_available is floored at zero"
    assert data["seats_reserved"] >= 0
    assert data["waitlist_count"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "BOOKED", "WAITLISTED", "CHECKED_IN", "CANCELLED", "NO_SHOW")
    assert data["price_paid_cents"] >= 0


def assert_permit_allocation(data: dict):
    _assert_common(data)
    assert data["issued_count"] >= 0
    assert data["available_quota"] >= 0, "available_quota is floored at zero"


def assert_permit_pass(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "EXPIRED")


def assert_seats_conserved(trip: dict):
    """Invariant: seats_reserved + seats_available == capacity (PRD §3.5)."""
    assert trip["seats_reserved"] + trip["seats_available"] == trip["capacity"], (
        f"seats_reserved({trip['seats_reserved']}) + "
        f"seats_available({trip['seats_available']}) must equal capacity({trip['capacity']})"
    )
