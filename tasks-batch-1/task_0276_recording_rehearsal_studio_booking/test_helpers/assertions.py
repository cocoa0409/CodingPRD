"""Entity assertions and domain invariant checkers.

Validate response shapes against the PRD contract (§2.4 common fields, §2.7 status
dimensions, §3 entity fields). Uses the framework's generic format validators.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


_SCHEDULE_STATES = {"HELD", "CONFIRMED", "IN_SESSION", "COMPLETED", "CANCELLED"}
_SETTLEMENT_STATES = {"AWAITING_DEPOSIT", "DEPOSIT_PAID", "BALANCE_DUE", "SETTLED", "REFUNDING", "REFUNDED"}


def _assert_common(data: dict):
    """id/created_at/updated_at/version present for common_fields:true entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_studio(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["deposit_pct"], (int, float))
    assert 0 < data["deposit_pct"] <= 1
    assert isinstance(data["overtime_multiplier"], (int, float))
    assert data["overtime_multiplier"] >= 1
    assert isinstance(data["overtime_grace_minutes"], int) and data["overtime_grace_minutes"] >= 0
    assert isinstance(data["cancellation_tier_hours"], int) and data["cancellation_tier_hours"] >= 0
    assert isinstance(data["late_cancel_fee_pct"], (int, float))
    assert 0 <= data["late_cancel_fee_pct"] <= 1


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["block_rate_cents"], int) and data["block_rate_cents"] >= 0
    assert isinstance(data["block_hours"], int) and data["block_hours"] >= 1
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0
    assert data["status"] in {"OPEN", "LOCKED"}


def assert_engineer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["tier"] in {"ASSISTANT", "STAFF", "SENIOR"}
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_gear_item(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert isinstance(data["requires_engineer"], bool)


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["schedule_status"] in _SCHEDULE_STATES, f"bad schedule_status {data.get('schedule_status')!r}"
    assert data["settlement_status"] in _SETTLEMENT_STATES, f"bad settlement_status {data.get('settlement_status')!r}"
    assert data["booking_kind"] in {"HOURLY", "BLOCK", "LOCKOUT"}
    assert isinstance(data["base_charge_cents"], int) and data["base_charge_cents"] >= 0
    assert isinstance(data["deposit_due_cents"], int) and data["deposit_due_cents"] >= 0
    assert isinstance(data["overtime_cents"], int) and data["overtime_cents"] >= 0
    assert isinstance(data["total_charge_cents"], int) and data["total_charge_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0


def assert_gear_rental(data: dict):
    _assert_common(data)
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["rental_days"], int) and data["rental_days"] >= 1
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0
    assert data["status"] in {"RESERVED", "RELEASED"}


def assert_engineer_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["scheduled_hours"], (int, float)) and data["scheduled_hours"] >= 0
    assert isinstance(data["billed_hours"], (int, float)) and data["billed_hours"] >= 0
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0
    assert data["status"] in {"ASSIGNED", "RELEASED"}


def assert_payment(data: dict):
    _assert_common(data)
    assert data["kind"] in {"DEPOSIT", "BALANCE", "REFUND"}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["refund_destination"] in {"ORIGINAL", "WALLET"}
    assert isinstance(data["reversed"], bool)


def assert_lockout_contract(data: dict):
    _assert_common(data)
    assert data["status"] in {"DRAFT", "ACTIVE", "TERMINATED"}
    assert isinstance(data["occurrences_generated"], int) and data["occurrences_generated"] >= 0
    assert isinstance(data["weekday_mask"], list) and len(data["weekday_mask"]) > 0


def assert_session_delivery(data: dict):
    _assert_common(data)
    assert data["status"] in {"DRAFT", "DELIVERED", "REVISION_REQUESTED", "ACCEPTED"}
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_overtime_record(data: dict):
    """OvertimeRecord is append-only (PRD §2.4): id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "OvertimeRecord must not expose a version field"
    assert "updated_at" not in data, "OvertimeRecord must not expose an updated_at field"
    assert isinstance(data["overage_minutes"], int) and data["overage_minutes"] >= 0
    assert isinstance(data["room_surcharge_cents"], int) and data["room_surcharge_cents"] >= 0
    assert isinstance(data["engineer_surcharge_cents"], int) and data["engineer_surcharge_cents"] >= 0
