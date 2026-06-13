"""Entity assertions and domain invariant checkers (Travel Agency Tour Booking API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields: id (UUID), created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["currency"], str) and len(data["currency"]) > 0
    assert is_iso8601_timestamp(data.get("now_utc", "")), "now_utc must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents never negative"


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["kind"] in ("FLIGHT", "HOTEL", "ACTIVITY")
    assert isinstance(data["auto_confirm"], bool)


def assert_tour_package(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["base_price_per_person_cents"], int)
    assert data["base_price_per_person_cents"] > 0
    assert isinstance(data["deposit_pct"], int)
    assert 1 <= data["deposit_pct"] <= 100
    assert isinstance(data["balance_due_days_before_departure"], int)
    assert data["balance_due_days_before_departure"] >= 0
    assert isinstance(data["min_group_size_for_discount"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["tour_package_id"], str)
    assert isinstance(data["traveler_count"], int) and data["traveler_count"] >= 0
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["insurance_premium_cents"], int) and data["insurance_premium_cents"] >= 0
    assert isinstance(data["grand_total_cents"], int) and data["grand_total_cents"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert data["status"] in ("DRAFT", "RESERVED", "CONFIRMED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL")


def assert_traveler(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["is_lead"], bool)


def assert_component(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert data["kind"] in ("FLIGHT", "HOTEL", "ACTIVITY")
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["is_mandatory"], bool)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "REJECTED", "RELEASED")


def assert_milestone(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert data["kind"] in ("DEPOSIT", "BALANCE")
    assert isinstance(data["amount_due_cents"], int)
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data["settled_amount_cents"], int) and data["settled_amount_cents"] >= 0
    assert data["status"] in ("OPEN", "SETTLED", "WAIVED")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["milestone_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CARD", "WALLET", "BANK_TRANSFER")
    assert data["status"] in ("APPLIED", "REFUNDED")


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert data["coverage_tier"] in ("BASIC", "PREMIUM")
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] >= 0
    assert isinstance(data["refundable"], bool)
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_cancellation_record(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert is_iso8601_timestamp(data.get("cancelled_at", ""))
    assert data["penalty_tier"] in ("TIER_FREE", "TIER_LOW", "TIER_HIGH", "TIER_FULL")
    assert isinstance(data["penalty_pct"], int)
    assert isinstance(data["refundable_base_cents"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert data["refund_destination"] in ("WALLET", "ORIGINAL")
