"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates id/timestamp shape and the field set the PRD
guarantees on that entity. ServicePlan is the only entity without version/
updated_at (it is an immutable price card per PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields shared by every versioned entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_service_plan(data: dict):
    # Immutable price card: id + created_at only, no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ServicePlan must NOT carry a version field"
    assert "updated_at" not in data, "ServicePlan must NOT carry an updated_at field"
    assert data["billing_model"] in ("PER_MINUTE", "PER_CALL")
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["overage_rate_cents"], int)
    assert isinstance(data["overage_tier2_rate_cents"], int)
    assert isinstance(data["hard_cap_overage_cents"], int)


def assert_account(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DELINQUENT", "SUSPENDED")
    assert data["default_language"] in ("EN", "ES")
    assert isinstance(data["open_call_count"], int)
    assert isinstance(data["lifetime_calls_answered"], int)


def assert_call_script(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")
    assert data["after_hours_action"] in ("VOICEMAIL", "OVERFLOW")
    assert data["overflow_action"] in ("QUEUE", "VOICEMAIL")


def assert_spam_rule(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DISABLED")
    assert isinstance(data["blocked_area_codes"], list)


def assert_receptionist(data: dict):
    _assert_common(data)
    assert data["status"] in ("OFFLINE", "AVAILABLE", "BUSY")
    assert isinstance(data["languages"], list) and len(data["languages"]) > 0
    assert isinstance(data["active_call_count"], int)


def assert_availability_window(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_calendar_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert_slot_capacity_invariant(data)


def assert_call(data: dict):
    _assert_common(data)
    assert data["handling_status"] in (
        "RINGING", "ANSWERED", "IN_PROGRESS", "WRAP_UP",
        "COMPLETED", "OVERFLOW", "SCREENED_OUT", "ABANDONED",
    )
    assert data["billing_status"] in ("UNBILLED", "BILLED", "DISPUTED", "ADJUSTED")
    assert isinstance(data["duration_seconds"], int)
    assert isinstance(data["billed_units"], int)
    assert isinstance(data["charge_cents"], int)


def assert_message(data: dict):
    _assert_common(data)
    assert data["status"] in ("NEW", "HANDED_OFF")


def assert_escalation(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUEUED", "ASSIGNED", "RESOLVED")
    assert data["reason"] in ("LONG_RUNNING", "CALLER_REQUEST", "LANGUAGE")


def assert_crm_handoff(data: dict):
    _assert_common(data)
    assert data["status"] in ("PUSHED", "FAILED")
    assert isinstance(data["messages_pushed"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED",
        "COMPLETED", "CANCELLED", "NO_SHOW",
    )
    assert isinstance(data["reschedule_count"], int)


def assert_billing_period(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PENDING_CLOSE", "CLOSED")
    assert isinstance(data["consumed_units"], int)
    assert isinstance(data["overage_units"], int)
    assert isinstance(data["overage_charge_cents"], int)


# --- Domain invariant checkers ----------------------------------------------
def assert_slot_capacity_invariant(slot: dict):
    """available_count == capacity - booked_count, and never negative (PRD §3.12)."""
    assert slot["available_count"] >= 0, "available_count must never be negative"
    assert slot["available_count"] == slot["capacity"] - slot["booked_count"], (
        f"available_count {slot['available_count']} != capacity "
        f"{slot['capacity']} - booked_count {slot['booked_count']}"
    )


def assert_overage_arithmetic(period_or_summary: dict, included_units: int,
                              tier2_threshold: int, r1: int, r2: int):
    """Recompute the tiered overage from consumed_units and confirm it matches
    the persisted/returned overage_units and overage_charge_cents (PRD §3.8)."""
    consumed = period_or_summary["consumed_units"]
    overage_units = max(0, consumed - included_units)
    tier1 = min(overage_units, tier2_threshold - 1)
    tier2 = max(0, overage_units - (tier2_threshold - 1))
    expected_charge = tier1 * r1 + tier2 * r2
    assert period_or_summary["overage_units"] == overage_units, (
        f"overage_units {period_or_summary['overage_units']} != expected {overage_units}"
    )
    assert period_or_summary["overage_charge_cents"] == expected_charge, (
        f"overage_charge_cents {period_or_summary['overage_charge_cents']} != "
        f"expected {expected_charge}"
    )
