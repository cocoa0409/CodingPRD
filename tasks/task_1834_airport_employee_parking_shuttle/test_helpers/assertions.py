"""Entity assertions and domain invariant checkers.

Logical-clock timestamps are compared as instants, not strings: the PRD pins
the instant ("stamps X with the current logical time") while the exact string
rendering of a datetime is the implementer's choice.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware datetime."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant_equals(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO-8601 timestamps denote the same instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["posture"] in ("PROGRAM_NORMAL", "PROGRAM_FROZEN", "PROGRAM_CLOSED")
    assert data["proration_mode"] in ("CALENDAR_DAY", "HALF_MONTH")
    assert isinstance(data["monthly_subsidy_pool_cents"], int)
    assert data["monthly_subsidy_pool_cents"] >= 0
    assert isinstance(data["waitlist_offer_ttl_hours"], int)
    assert data["waitlist_offer_ttl_hours"] > 0
    assert isinstance(data["violation_suspension_threshold"], int)
    assert data["violation_suspension_threshold"] >= 1
    assert isinstance(data["tow_hold_hours"], int)
    assert data["tow_hold_hours"] >= 0
    assert isinstance(data["ops_run_index"], int)


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["badge_number"], str) and data["badge_number"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["employer_code"], str)
    assert data["shift_pattern"] in ("DAY", "NIGHT", "ROTATING", "SPLIT")
    assert isinstance(data["hire_date"], str)
    assert data["employment_status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["balance_due_cents"], int)
    assert data["balance_due_cents"] >= 0, "balance_due_cents is never negative"
    assert data["standing"] in ("GOOD_STANDING", "BILLING_HOLD")
    # Domain invariant: standing mirrors the balance.
    if data["balance_due_cents"] > 0:
        assert data["standing"] == "BILLING_HOLD"
    else:
        assert data["standing"] == "GOOD_STANDING"


def assert_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["code"], str) and data["code"]
    assert data["tier"] in ("CORE", "REMOTE")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 0
    assert isinstance(data["monthly_maintenance_cents"], int)
    assert data["status"] in ("ACTIVE", "STANDBY", "ACTIVATED", "CLOSED")
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0
    assert isinstance(data["reserved_slots"], int) and data["reserved_slots"] >= 0


def assert_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["vehicle_plate"], str)
    assert data["queue_shift_pattern"] in ("DAY", "NIGHT", "ROTATING", "SPLIT")
    assert data["status"] in (
        "REQUESTED", "WAITLISTED", "OFFERED", "ACTIVE", "SUSPENDED",
        "REVOKED", "DECLINED", "EXPIRED", "CANCELLED",
    )


def assert_renewal(data: dict):
    _assert_common(data)
    assert isinstance(data["permit_id"], str)
    assert data["status"] in (
        "PENDING", "APPROVED", "REJECTED", "SUPERSEDED", "EXPIRED"
    )


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["headway_target_minutes"], int)
    assert data["headway_target_minutes"] > 0
    assert isinstance(data["operating_cost_per_trip_cents"], int)
    assert data["operating_cost_per_trip_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_trip(data: dict):
    _assert_common(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["scheduled_departure_at"], str)
    assert data["status"] in ("SCHEDULED", "DEPARTED", "COMPLETED", "CANCELLED")
    assert isinstance(data["boarded_count"], int) and data["boarded_count"] >= 0


def assert_notice(data: dict):
    _assert_common(data)
    assert data["notice_type"] in (
        "LOT_CLOSURE", "LOT_REOPEN", "ROUTE_SUSPENSION", "HEADWAY_CHANGE", "GENERAL"
    )
    assert isinstance(data["headline"], str)
    assert isinstance(data["effective_from"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "EFFECTIVE", "CANCELLED")


def assert_violation(data: dict):
    _assert_common(data)
    assert isinstance(data["permit_id"], str)
    assert data["violation_code"] in (
        "EXPIRED_PERMIT", "WRONG_LOT", "NO_PERMIT_DISPLAY",
        "BLOCKED_LANE", "PARKED_AFTER_REVOCATION",
    )
    assert isinstance(data["issued_by"], str)
    assert isinstance(data["fine_cents"], int)
    assert data["payment_status"] in ("UNPAID", "PAID", "REVERSED")
    assert data["appeal_status"] in ("NONE", "APPEALED", "UPHELD", "DISMISSED")


def assert_tow_event(data: dict):
    _assert_common(data)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["violation_id"], str)
    assert isinstance(data["authorized_by"], str)
    assert data["status"] in ("AUTHORIZED", "TOWED", "RELEASED", "CANCELLED")


def assert_billing_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in ("OPEN", "CLOSED", "EXPORTED")
    assert isinstance(data["subsidy_per_capita_cap_cents"], int)
    assert isinstance(data["total_charges_cents"], int)


def assert_charge_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["employee_id"], str)
    assert data["charge_type"] in (
        "PERMIT_FEE", "VIOLATION_FINE", "TOW_FEE",
        "ADJUSTMENT_CREDIT", "ADJUSTMENT_DEBIT",
    )
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in (
        "PENDING", "APPLIED", "EXPORTED", "SETTLED", "DEDUCTION_FAILED", "REVERSED"
    )


def assert_peak_window(data: dict):
    _assert_common(data)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "ENDED", "CANCELLED")


def sum_non_reversed(entries: list) -> int:
    """Domain invariant helper: a cycle's total is the plain integer sum of
    its entries not in REVERSED status."""
    return sum(e["amount_cents"] for e in entries if e["status"] != "REVERSED")
