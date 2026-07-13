"""Entity assertions and domain invariant checkers for the Boat Club API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Common system fields carried by every non-config entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_dock(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["location_code"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["is_reciprocal"], bool)


def assert_membership_tier(data: dict):
    """MembershipTier is a config record: id + created_at only (no updated_at/version)."""
    assert isinstance(data.get("id"), str) and len(data["id"]) > 0
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier_code"] in ("CRUISE", "SAIL", "UNLIMITED")
    assert isinstance(data["monthly_dues_cents"], int) and data["monthly_dues_cents"] >= 0
    assert isinstance(data["max_active_reservations"], int) and data["max_active_reservations"] >= 1
    assert isinstance(data["reservations_per_week"], int) and data["reservations_per_week"] >= 1
    assert isinstance(data["reciprocal_access_allowed"], bool)
    assert isinstance(data["advance_booking_days_max"], int) and data["advance_booking_days_max"] >= 1


def assert_member(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING_ORIENTATION", "ACTIVE", "SUSPENDED", "CANCELLED")
    assert data["certification_level"] in ("NONE", "BASIC", "ADVANCED")
    assert isinstance(data["orientation_completed"], bool)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["membership_tier"] in ("CRUISE", "SAIL", "UNLIMITED")


def assert_boat(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("AVAILABLE", "OUT", "CLEANING", "MAINTENANCE")
    assert data["boat_type"] in ("PONTOON", "BOWRIDER", "DECK_BOAT", "CENTER_CONSOLE")
    assert isinstance(data["usage_count"], int) and data["usage_count"] >= 0
    assert isinstance(data["needs_cleaning"], bool)


def assert_reservation(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "CHECKED_OUT", "RETURNED", "NO_SHOW", "CANCELLED"
    )
    assert data["boat_type"] in ("PONTOON", "BOWRIDER", "DECK_BOAT", "CENTER_CONSOLE")


def assert_fee(data: dict):
    assert_common_fields(data)
    assert data["fee_type"] in ("NO_SHOW", "LATE_RETURN", "FUEL", "CLEANING", "DAMAGE")
    assert data["status"] in ("ASSESSED", "WAIVED", "PAID")
    assert isinstance(data["amount_cents"], int)


def assert_dues_invoice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ISSUED", "OVERDUE", "PAID", "VOID")
    assert isinstance(data["base_dues_cents"], int)


def assert_fee_ledger_conserved(member: dict, total: int):
    """PRD §3.6: outstanding + waived + paid always sum to the member's total fee amount."""
    s = member["outstanding_fees_cents"] + member["waived_fees_cents"] + member["paid_fees_cents"]
    assert s == total, f"fee ledger not conserved: {s} != {total}"
