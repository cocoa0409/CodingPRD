"""Entity assertions and domain invariant checkers for Kids Venue Booking."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC string into a timezone-aware instant.

    PRD 2.9 specifies only that event times are "ISO 8601 UTC"; unlike created_at /
    updated_at (PRD 2.4: "three fractional digits"), the PRD does not pin the
    fractional-digit count for event_start_utc / event_end_utc, so both
    `...:00Z` and `...:00.000Z` are valid serializations of the same instant.
    """
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_eq(actual: str, expected: str):
    """Assert two ISO 8601 UTC timestamps denote the same instant.

    Compares the parsed instant rather than the raw string, because the PRD does
    not pin the fractional-digit serialization of event_start_utc / event_end_utc
    (PRD 2.9: "Times are ISO 8601 UTC"). The computed *value* is PRD-derivable; the
    exact serialized format is not.
    """
    assert is_iso8601_timestamp(actual), "value must be ISO 8601: %r" % (actual,)
    assert _parse_instant(actual) == _parse_instant(expected), (
        "instant mismatch: %r != %r" % (actual, expected)
    )


def assert_venue(data: dict):
    assert is_valid_uuid(data.get("id", "")), "venue id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)
    assert isinstance(data["weather_dependent"], bool)
    assert isinstance(data["reschedule_lead_hours"], int)
    assert data["status"] == "ACTIVE"
    assert isinstance(data.get("version"), int)


def assert_room(data: dict):
    assert is_valid_uuid(data.get("id", "")), "room id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be valid UUID"
    assert isinstance(data["name"], str)
    assert data["room_kind"] in ("INDOOR", "OUTDOOR")
    assert isinstance(data["max_capacity"], int) and data["max_capacity"] >= 1
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data.get("version"), int)


def assert_package(data: dict):
    assert is_valid_uuid(data.get("id", "")), "package id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be valid UUID"
    assert isinstance(data["theme"], str)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["included_children"], int) and data["included_children"] >= 1
    assert isinstance(data["per_extra_child_cents"], int) and data["per_extra_child_cents"] >= 0
    assert isinstance(data["base_duration_minutes"], int)
    assert 0 < float(data["deposit_pct"]) <= 1
    assert data["status"] in ("LISTED", "RETIRED")


def assert_staff_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "staff id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be valid UUID"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["skills"], list)
    assert data["status"] in ("AVAILABLE", "INACTIVE")


def assert_booking(data: dict):
    """Validate a Booking response against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "booking id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be valid UUID"
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be valid UUID"
    assert is_valid_uuid(data.get("package_id", "")), "package_id must be valid UUID"
    assert is_iso8601_timestamp(data.get("event_start_utc", "")), "event_start_utc ISO 8601"
    assert is_iso8601_timestamp(data.get("event_end_utc", "")), "event_end_utc ISO 8601"
    assert isinstance(data["effective_duration_minutes"], int)
    assert isinstance(data["children_count"], int) and data["children_count"] >= 1
    assert isinstance(data["adults_count"], int) and data["adults_count"] >= 0
    assert data["headcount_committed"] == data["children_count"] + data["adults_count"]
    assert data["waivers_required"] == data["children_count"]
    assert isinstance(data["waivers_signed"], int) and data["waivers_signed"] >= 0
    assert isinstance(data["quote_total_cents"], int) and data["quote_total_cents"] >= 0
    assert isinstance(data["deposit_due_cents"], int) and data["deposit_due_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED")
    assert isinstance(data["weather_eligible"], bool)
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert data["status"] in (
        "QUOTE_DRAFT", "HELD", "CONFIRMED", "WEATHER_HOLD",
        "RESCHEDULED", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data.get("version"), int)


def assert_add_on(data: dict):
    assert is_valid_uuid(data.get("id", "")), "addon id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be valid UUID"
    assert data["kind"] in ("CAKE", "CHARACTER", "EXTRA_TIME")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["extra_minutes"], int)
    assert data["requires_skill"] in ("ENTERTAINER", "COOK", "NONE")
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_waiver(data: dict):
    assert is_valid_uuid(data.get("id", "")), "waiver id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be valid UUID"
    assert isinstance(data["child_name"], str)
    assert data["status"] in ("DRAFT", "SIGNED", "VOIDED")


def assert_staff_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "assignment id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be valid UUID"
    assert is_valid_uuid(data.get("staff_member_id", "")), "staff_member_id must be valid UUID"
    assert data["role_on_event"] in ("HOST", "ENTERTAINER", "COOK")
    assert data["status"] in ("ASSIGNED", "RELEASED")


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "payment id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be valid UUID"
    assert data["direction"] in ("CHARGE", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["purpose"] in ("DEPOSIT", "BALANCE", "CANCELLATION_REFUND")
    assert data["status"] in ("SETTLED", "VOIDED")


def assert_guest_party(data: dict):
    """GuestParty is append-only: only id + created_at among common fields."""
    assert is_valid_uuid(data.get("id", "")), "guest_party id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be valid UUID"
    assert isinstance(data["children_delta"], int)
    assert isinstance(data["adults_delta"], int)


def assert_booking_money_conserved(data: dict):
    """Money invariant: balance_due_cents == applicable_total - amount_paid_cents.

    The applicable total is final_total_cents once COMPLETED, else quote_total_cents.
    """
    if data["status"] == "COMPLETED":
        target = data["final_total_cents"]
    else:
        target = data["quote_total_cents"]
    assert data["balance_due_cents"] == target - data["amount_paid_cents"], (
        f"balance_due_cents {data['balance_due_cents']} must equal "
        f"target {target} - amount_paid_cents {data['amount_paid_cents']}"
    )
