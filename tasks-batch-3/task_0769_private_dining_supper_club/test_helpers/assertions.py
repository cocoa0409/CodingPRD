"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

EVENT_STATUSES = ["DRAFT", "SCHEDULED", "OPEN", "SUSPENDED", "COMPLETED", "CANCELLED"]
SEAT_STATUSES = ["AVAILABLE", "HELD", "BOOKED", "BLOCKED"]
SEAT_TYPES = ["STANDARD", "ACCESSIBLE", "HEAD_TABLE"]
BOOKING_STATUSES = ["PENDING_DEPOSIT", "CONFIRMED", "ATTENDED", "CANCELLED", "NO_SHOW"]
PAYMENT_STATUSES = ["UNPAID", "DEPOSIT_PAID", "REFUNDED", "PARTIALLY_REFUNDED", "FORFEITED"]
WAITLIST_STATUSES = ["WAITING", "PROMOTED", "WITHDRAWN", "EXPIRED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_event(data: dict):
    _assert_common(data)
    assert data["status"] in EVENT_STATUSES, f"unexpected event status {data['status']!r}"
    assert data["table_mode"] in ["COMMUNAL", "PRIVATE"]
    for f in ("seat_capacity", "seat_price_cents", "confirmed_seat_count",
              "available_seat_count", "gross_deposit_held_cents",
              "projected_revenue_cents", "realized_revenue_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_seat(data: dict):
    _assert_common(data)
    assert data["status"] in SEAT_STATUSES, f"unexpected seat status {data['status']!r}"
    assert data["seat_type"] in SEAT_TYPES, f"unexpected seat_type {data['seat_type']!r}"


def assert_booking(data: dict):
    _assert_common(data)
    assert data["booking_status"] in BOOKING_STATUSES
    assert data["payment_status"] in PAYMENT_STATUSES
    for f in ("deposit_due_cents", "deposit_paid_cents", "total_price_cents",
              "corkage_due_cents", "refund_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert data["status"] in WAITLIST_STATUSES


def assert_payment(data: dict):
    """Payment is an append-only ledger entry: only id + created_at, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "payment id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ["DEPOSIT", "REFUND"]
    assert data["direction"] in ["CHARGE", "REFUND"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
