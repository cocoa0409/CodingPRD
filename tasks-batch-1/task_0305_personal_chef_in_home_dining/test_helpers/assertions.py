"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CHEF_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED"]
BOOKING_LIFECYCLE = ["REQUESTED", "CONFIRMED", "IN_PREP", "COMPLETED", "DECLINED", "CANCELLED"]
BOOKING_PAYMENT = ["UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED"]
GROCERY_RUN_STATUSES = ["OPEN", "FINALIZED", "VOIDED"]
PAYMENT_STATUSES = ["CAPTURED", "REFUNDED"]
PLAN_STATUSES = ["ACTIVE", "PAUSED", "CANCELLED"]
RESCHEDULE_STATUSES = ["PROPOSED", "ACCEPTED", "REJECTED", "WITHDRAWN"]
BLOCK_KINDS = ["BLACKOUT", "BOOKING_HOLD"]
BLOCK_STATUSES = ["HELD", "RELEASED"]


def _assert_common(data: dict):
    """PRD §2.4: every entity carries id (UUID), created_at, updated_at (ISO 8601),
    and integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_chef(data: dict):
    _assert_common(data)
    assert data["status"] in CHEF_STATUSES, f"unexpected chef status {data['status']!r}"
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["prep_buffer_minutes"], int) and data["prep_buffer_minutes"] >= 0
    assert isinstance(data["max_bookings_per_day"], int) and data["max_bookings_per_day"] >= 1
    assert isinstance(data["completed_bookings_count"], int)
    assert isinstance(data["settled_reliability_score"], int)
    assert isinstance(data["projected_reliability_score"], int)
    assert isinstance(data["active_booking_count"], int)


def assert_chef_payout_invariant(data: dict):
    """PRD §2.10 / §3.6: payout_accrued_cents == captured_payments_cents -
    refunded_payments_cents, always."""
    assert data["payout_accrued_cents"] == data["captured_payments_cents"] - data["refunded_payments_cents"], (
        f"payout invariant violated: payout={data['payout_accrued_cents']} "
        f"captured={data['captured_payments_cents']} refunded={data['refunded_payments_cents']}"
    )


def assert_menu(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["base_price_per_guest_cents"], int)
    assert isinstance(data["estimated_ingredient_per_guest_cents"], int)
    assert isinstance(data["is_listed"], bool)


def assert_travel_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["travel_fee_cents"], int)


def assert_availability_block(data: dict):
    _assert_common(data)
    assert data["kind"] in BLOCK_KINDS
    assert data["status"] in BLOCK_STATUSES


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)


def assert_booking(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in BOOKING_LIFECYCLE
    assert data["payment_status"] in BOOKING_PAYMENT
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["quote_total_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["amount_captured_cents"], int)


def assert_grocery_run(data: dict):
    _assert_common(data)
    assert data["status"] in GROCERY_RUN_STATUSES
    assert isinstance(data["raw_actual_subtotal_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["kind"] in ["DEPOSIT", "BALANCE"]
    assert data["status"] in PAYMENT_STATUSES
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_recurring_plan(data: dict):
    _assert_common(data)
    assert data["status"] in PLAN_STATUSES
    assert isinstance(data["occurrences_generated"], int)


def assert_reschedule_request(data: dict):
    _assert_common(data)
    assert data["status"] in RESCHEDULE_STATUSES
