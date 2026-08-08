"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (``is_valid_uuid``,
``is_iso8601_timestamp``) internally. Balance/ledger invariants are checked
with plain integer-cent comparisons (all money is whole cents).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _managed(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _immutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable record must not carry updated_at"
    assert "version" not in data, "immutable record must not carry version"


def assert_property(data: dict):
    _managed(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["guest_parking_capacity"], int) and data["guest_parking_capacity"] >= 0


def assert_unit(data: dict):
    _managed(data)
    assert data["occupancy_status"] in ("VACANT", "OCCUPIED")


def assert_resident(data: dict):
    _managed(data)
    assert data["account_status"] in ("GOOD_STANDING", "DELINQUENT", "SUSPENDED")
    assert data["membership_tier"] in ("STANDARD", "PREMIUM")
    assert_resident_balances(data)


def assert_resident_balances(data: dict):
    """Money invariants that must hold on any resident snapshot."""
    assert data["rent_balance_cents"] >= 0, "rent_balance_cents is never negative"
    assert data["hold_balance_cents"] >= 0, "hold_balance_cents is never negative"
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents is never negative"
    assert data["no_show_strikes"] >= 0
    assert 0 <= data["retention_score"] <= 100, "retention_score clamped to 0..100"


def assert_amenity(data: dict):
    _managed(data)
    assert data["amenity_type"] in ("GYM", "POOL", "CLUBROOM")
    assert data["status"] in ("OPEN", "CLOSED", "MAINTENANCE")
    assert data["capacity"] >= 1


def assert_booking(data: dict):
    _managed(data)
    assert data["status"] in (
        "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW", "SUSPENDED",
    )
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["deposit_hold_cents"], int)


def assert_event(data: dict):
    _managed(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED")
    assert data["reserved_count"] >= 0
    assert data["waitlist_count"] >= 0


def assert_registration(data: dict):
    _managed(data)
    assert data["status"] in ("RESERVED", "WAITLISTED", "ATTENDED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["fee_charged_cents"], int)


def assert_vendor(data: dict):
    _managed(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["trades"], list)
    assert data["active_job_count"] >= 0


def assert_service_request(data: dict):
    _managed(data)
    assert data["status"] in (
        "SUBMITTED", "TRIAGED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED",
    )
    assert data["priority"] in ("ROUTINE", "URGENT", "EMERGENCY")


def assert_package(data: dict):
    _managed(data)
    assert data["status"] in ("RECEIVED", "NOTIFIED", "PICKED_UP", "RETURNED")


def assert_guest_pass(data: dict):
    _managed(data)
    assert data["status"] in ("ISSUED", "CHECKED_IN", "DEPARTED", "EXPIRED", "CANCELLED")


def assert_survey(data: dict):
    _managed(data)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")
    assert data["response_count"] >= 0


def assert_ledger_entry(data: dict):
    _immutable(data)
    assert data["entry_type"] in (
        "RENT_CHARGE", "BOOKING_FEE", "DEPOSIT_FORFEIT", "EVENT_FEE",
        "SERVICE_CHARGE", "PENALTY", "PAYMENT", "REFUND",
    )
    assert isinstance(data["amount_cents"], int)


def assert_survey_response(data: dict):
    _immutable(data)
    assert 1 <= data["satisfaction_score"] <= 5
