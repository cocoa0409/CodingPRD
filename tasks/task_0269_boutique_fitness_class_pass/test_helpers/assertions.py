"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response structure against the PRD contract
using framework generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_quartet(data: dict):
    """id + created_at + updated_at + version (PRD section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_studio(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["active_room_count"], int) and data["active_room_count"] >= 0


def assert_room(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["studio_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["physical_capacity"], int) and data["physical_capacity"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_instructor(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data["home_studio_id"])
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_class_template(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["duration_min"], int) and 15 <= data["duration_min"] <= 240
    assert isinstance(data["credit_cost"], int) and data["credit_cost"] >= 1
    assert isinstance(data["late_cancel_window_hours"], int) and data["late_cancel_window_hours"] >= 0
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_package_plan(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("INTRO", "CREDIT_PACK", "MEMBERSHIP")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["grant_credits"], int) and data["grant_credits"] >= 1
    assert isinstance(data["validity_days"], int) and data["validity_days"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_member(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data["home_studio_id"])
    assert isinstance(data["has_used_intro"], bool)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["standing"] in ("GOOD", "RESTRICTED")


def assert_membership(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ("PENDING_PAYMENT", "ACTIVE", "FROZEN", "EXPIRED", "CANCELLED")
    assert isinstance(data["credit_balance"], int)
    assert isinstance(data["freeze_days_used"], int) and data["freeze_days_used"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0


def assert_class_session(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["studio_id"])
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert is_valid_uuid(data["template_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["waitlist_capacity"], int) and data["waitlist_capacity"] >= 0
    assert data["status"] in ("SCHEDULED", "OPEN", "FULL", "CANCELLED", "COMPLETED")
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert isinstance(data["waitlisted_count"], int) and data["waitlisted_count"] >= 0


def assert_reservation(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["membership_id"])
    assert data["booking_status"] in ("WAITLISTED", "BOOKED", "RELEASED")
    assert data["attendance_status"] in (
        "PENDING", "CHECKED_IN", "NO_SHOW", "CANCELLED", "LATE_CANCELLED",
    )
    assert isinstance(data["credits_charged"], int) and data["credits_charged"] >= 0
    assert isinstance(data["waitlist_position"], int) and data["waitlist_position"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0


def assert_fee_charge(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["reservation_id"])
    assert data["kind"] in ("LATE_CANCEL", "NO_SHOW")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("ASSESSED", "WAIVED")
    assert isinstance(data["credit_refunded"], bool)


def assert_wallet_entry(data: dict):
    """A WalletEntry is an immutable ledger record: id + created_at only,
    no updated_at and no version (PRD section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in (
        "GRANT", "RESERVE_DEBIT", "CANCEL_REFUND", "EXPIRY_FORFEIT", "ROLLOVER_FORFEIT",
    )
    assert isinstance(data["delta"], int)
    assert "updated_at" not in data, "WalletEntry must not carry updated_at"
    assert "version" not in data, "WalletEntry must not carry version"
