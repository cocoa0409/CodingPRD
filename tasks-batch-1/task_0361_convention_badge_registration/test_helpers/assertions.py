"""Entity assertions and domain invariant checkers.

Uses the framework's generic format validators internally. Field names are
PRD-exact. Every entity in this API carries id, created_at, updated_at, version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_convention(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data["event_start_utc"])
    assert is_iso8601_timestamp(data["event_end_utc"])
    assert isinstance(data["total_badge_capacity"], int) and data["total_badge_capacity"] >= 1
    assert isinstance(data["badges_issued_count"], int) and data["badges_issued_count"] >= 0
    assert data["posture"] in ("OPEN", "SOLD_OUT", "CLOSED")


def assert_ticket_type(data: dict):
    _assert_common(data)
    assert data["tier"] in ("GENERAL", "THREE_DAY", "VIP", "EXHIBITOR")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["tier_capacity"], int) and data["tier_capacity"] >= 1
    assert isinstance(data["tier_issued_count"], int) and data["tier_issued_count"] >= 0


def assert_attendee(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["loyalty_tier"] in ("NONE", "SILVER", "GOLD", "PLATINUM")
    assert data["status"] in ("ACTIVE", "BANNED")


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PENDING_PAYMENT", "PAID", "CANCELLED", "REFUNDED")
    for f in ("ticket_subtotal_cents", "processing_fee_cents", "total_cents",
              "amount_paid_cents", "refund_amount_cents", "provisional_refund_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"
        assert data[f] >= 0, f"{f} must be non-negative"
    assert isinstance(data["is_group"], bool)


def assert_badge(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PICKED_UP", "PRINTED", "VOID")
    assert data["rfid_status"] in ("UNASSIGNED", "ENCODED", "DEACTIVATED")
    assert isinstance(data["transfer_count"], int) and data["transfer_count"] >= 0


def assert_session(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["seats_taken"], int) and data["seats_taken"] >= 0
    assert isinstance(data["requires_vip"], bool)


def assert_session_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("CONFIRMED", "WAITLISTED", "CANCELLED")
    assert isinstance(data["waitlist_score"], int)


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["requested_quantity"], int) and data["requested_quantity"] >= 1
    assert isinstance(data["group_size"], int) and data["group_size"] >= 1
    assert isinstance(data["priority_score"], int)
    assert data["status"] in ("ENTERED", "WON", "LOST")


def assert_exhibitor(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str)
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["estimated_booth_cents"], int) and data["estimated_booth_cents"] >= 0
    assert isinstance(data["actual_booth_cents"], int) and data["actual_booth_cents"] >= 0


def assert_booth(data: dict):
    _assert_common(data)
    assert isinstance(data["booth_code"], str)
    assert data["zone"] in ("STANDARD", "PREMIUM", "ENDCAP")
    assert isinstance(data["setup_buffer_hours"], int) and data["setup_buffer_hours"] >= 0


def assert_booth_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "CHECKED_IN", "RELEASED")
    assert isinstance(data["requested_days"], int) and data["requested_days"] >= 1
    assert isinstance(data["occupied_days"], int) and data["occupied_days"] >= 0
