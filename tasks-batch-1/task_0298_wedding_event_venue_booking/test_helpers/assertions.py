"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract,
using the framework's generic format checkers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_VENUE_STATUSES = {"ACTIVE", "ARCHIVED"}
_BOOKING_STATUSES = {"INQUIRY", "HELD", "CONFIRMED", "GUARANTEED", "COMPLETED", "CANCELLED"}
_PAYMENT_STATUSES = {"UNPAID", "DEPOSIT_PAID", "PARTIALLY_PAID", "PAID_IN_FULL", "REFUNDED"}
_HOLD_STATUSES = {"HELD", "COMMITTED", "RELEASED"}
_MILESTONE_STATUSES = {"OPEN", "PARTIAL", "SETTLED", "WAIVED"}
_VENDOR_STATUSES = {"PENDING", "CLEARED", "REJECTED"}
_REQUEST_STATUSES = {"PROPOSED", "COUNTERED", "APPROVED", "DECLINED", "WITHDRAWN"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["cancellation_tier"] in {"STANDARD", "STRICT", "FLEXIBLE"}
    assert isinstance(data["force_majeure_fee_pct"], (int, float))
    assert data["status"] in _VENUE_STATUSES


def assert_space(data: dict):
    _assert_common(data)
    assert data["space_kind"] in {"CEREMONY", "RECEPTION", "DUAL"}
    assert isinstance(data["max_capacity"], int) and data["max_capacity"] >= 1
    assert isinstance(data["base_rental_cents"], int) and data["base_rental_cents"] >= 0
    assert isinstance(data["turnover_buffer_minutes"], int) and data["turnover_buffer_minutes"] >= 0
    assert data["status"] in _VENUE_STATUSES


def assert_package(data: dict):
    _assert_common(data)
    assert data["tier"] in {"SILVER", "GOLD", "PLATINUM"}
    assert isinstance(data["per_head_cents"], int) and data["per_head_cents"] >= 0
    assert isinstance(data["fb_minimum_cents"], int) and data["fb_minimum_cents"] >= 0
    assert data["status"] in _VENUE_STATUSES


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_coordinator(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["active_booking_cap"], int) and data["active_booking_cap"] >= 1
    assert isinstance(data["assigned_active_count"], int) and data["assigned_active_count"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["booking_status"] in _BOOKING_STATUSES
    assert data["payment_status"] in _PAYMENT_STATUSES
    assert isinstance(data["expected_guest_count"], int) and data["expected_guest_count"] >= 1
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["event_charge_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_booking_balance_reconciles(data: dict):
    """balance_due_cents == event_charge_cents - amount_paid_cents (PRD §3.5)."""
    expected = data["event_charge_cents"] - data["amount_paid_cents"]
    assert data["balance_due_cents"] == expected, (
        f"balance_due_cents {data['balance_due_cents']} != "
        f"event_charge_cents {data['event_charge_cents']} - "
        f"amount_paid_cents {data['amount_paid_cents']} ({expected})"
    )


def assert_space_hold(data: dict):
    _assert_common(data)
    assert data["hold_status"] in _HOLD_STATUSES
    assert data["block_role"] in {"CEREMONY", "RECEPTION"}


def assert_milestone(data: dict):
    _assert_common(data)
    assert data["kind"] in {"DEPOSIT", "INTERIM", "FINAL"}
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert isinstance(data["amount_allocated_cents"], int) and data["amount_allocated_cents"] >= 0
    assert data["milestone_status"] in _MILESTONE_STATUSES


def assert_payment(data: dict):
    """Payment is the lean ledger entity: id + created_at, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Payment must NOT carry a version field"
    assert "updated_at" not in data, "Payment must NOT carry an updated_at field"
    assert data["direction"] in {"INBOUND", "OUTBOUND"}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in {"POSTED", "VOIDED"}


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["vendor_role"] in {"CATERING", "FLORAL", "PHOTOGRAPHY", "MUSIC", "RENTAL", "OTHER"}
    assert data["vendor_status"] in _VENDOR_STATUSES
    assert isinstance(data["coi_on_file"], bool)


def assert_guarantee(data: dict):
    _assert_common(data)
    assert isinstance(data["guaranteed_count"], int) and data["guaranteed_count"] >= 1


def assert_walkthrough(data: dict):
    _assert_common(data)
    assert data["walkthrough_status"] in {"SCHEDULED", "COMPLETED", "CANCELLED"}


def assert_reschedule_request(data: dict):
    _assert_common(data)
    assert data["reason_kind"] in {"CLIENT_REQUEST", "FORCE_MAJEURE"}
    assert data["request_status"] in _REQUEST_STATUSES
