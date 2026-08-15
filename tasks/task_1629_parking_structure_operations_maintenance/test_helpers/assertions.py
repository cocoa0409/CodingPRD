"""Entity assertions and domain invariant checkers.

Each assert_* validates the common system-managed properties (id, created_at,
updated_at, version) plus the entity's status field membership and a few
load-bearing fields named by the PRD. Assertions are intentionally limited to
field presence/type/membership so they never demand more than the PRD states.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["total_spaces"], int) and data["total_spaces"] > 0
    assert isinstance(data["monthly_capacity"], int) and data["monthly_capacity"] >= 0
    assert isinstance(data["event_pool_spaces"], int) and data["event_pool_spaces"] >= 0
    assert data["posture"] in (
        "NORMAL", "EVENT_SURGE", "RESTRICTED", "CLOSED_TEMPORARY", "DECOMMISSIONED")
    assert isinstance(data["closed_spaces"], int)
    assert isinstance(data["capital_reserve_cents"], int)
    assert isinstance(data["deposit_liability_cents"], int)
    assert isinstance(data["cumulative_collected_cents"], int)


def assert_rate_schedule(data: dict):
    _assert_common(data)
    assert data["schedule_status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED")
    assert isinstance(data["grace_minutes"], int) and data["grace_minutes"] >= 0
    assert isinstance(data["first_hour_cents"], int) and data["first_hour_cents"] >= 0
    assert isinstance(data["additional_hour_cents"], int)
    assert isinstance(data["daily_max_cents"], int) and data["daily_max_cents"] > 0
    assert data["cap_mode"] in ("CALENDAR_DAY", "ROLLING_24H")


def assert_access_device(data: dict):
    _assert_common(data)
    assert data["device_kind"] in ("ENTRY_GATE", "EXIT_GATE", "PAY_STATION")
    assert data["device_status"] in ("OFFLINE", "ONLINE", "DEGRADED", "DECOMMISSIONED")
    assert data["device_mode"] in ("STANDARD", "EVENT")


def assert_parker_account(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_monthly_agreement(data: dict):
    _assert_common(data)
    assert data["tier"] in ("STANDARD", "PREMIUM", "EV")
    assert data["agreement_status"] in (
        "SUBMITTED", "APPROVED", "WAITLISTED", "ACTIVE", "SUSPENDED",
        "TERMINATED", "WITHDRAWN")
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] > 0
    assert isinstance(data["application_seq"], int)


def assert_credential(data: dict):
    _assert_common(data)
    assert data["credential_type"] in ("BADGE", "TRANSPONDER")
    assert data["credential_status"] in (
        "ACTIVE", "LOST_REPORTED", "REPLACED", "RETURNED", "REVOKED")
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0


def assert_parking_session(data: dict):
    _assert_common(data)
    assert data["occupancy_state"] in ("PARKED", "EXITED")
    assert data["billing_state"] in ("OPEN", "QUOTED", "SETTLED", "COMPED", "REFUNDED")
    assert data["fee_mode"] in ("STANDARD", "EVENT_FLAT", "LOST_TICKET", "MONTHLY")
    assert is_iso8601_timestamp(data.get("entry_at", ""))


def assert_attendant_shift(data: dict):
    _assert_common(data)
    assert data["shift_status"] in ("OPEN", "CLOSED", "FORCE_CLOSED", "RECONCILED")
    assert isinstance(data["opening_float_cents"], int) and data["opening_float_cents"] >= 0
    assert isinstance(data["attendant_user_id"], str) and data["attendant_user_id"]


def assert_reconciliation(data: dict):
    _assert_common(data)
    assert data["reconciliation_status"] in (
        "DRAFT", "SUBMITTED", "VARIANCE_REVIEW", "APPROVED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["inspection_status"] in ("SCHEDULED", "IN_FIELD", "REPORTED", "CANCELLED")
    assert isinstance(data["level_scope"], str) and data["level_scope"]


def assert_repair_project(data: dict):
    _assert_common(data)
    assert data["project_status"] in (
        "PROPOSED", "FUNDED", "SCHEDULED", "IN_PROGRESS", "DEFERRED",
        "CLOSED_OUT", "CANCELLED")
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] > 0
    assert isinstance(data["revision_count"], int)


def assert_maintenance_window(data: dict):
    _assert_common(data)
    assert data["window_type"] in (
        "SWEEPING", "DRAIN_FLUSH", "LIGHTING_REPAIR", "SEALANT_WORK")
    assert data["window_status"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "MISSED", "CANCELLED")


def assert_patrol_round(data: dict):
    _assert_common(data)
    assert data["patrol_status"] in ("SCHEDULED", "COMPLETED", "MISSED")
    assert isinstance(data["officer_user_id"], str) and data["officer_user_id"]


def assert_incident(data: dict):
    _assert_common(data)
    assert data["incident_type"] in (
        "SECURITY", "VEHICLE_DAMAGE", "CASH_VARIANCE", "VANDALISM", "SAFETY")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["incident_status"] in ("OPEN", "INVESTIGATING", "RESOLVED", "CLOSED")
    assert isinstance(data["auto_created"], bool)


def assert_ev_charger(data: dict):
    _assert_common(data)
    assert data["charger_status"] in (
        "PROPOSED", "PERMITTED", "INSTALLED", "COMMISSIONED",
        "OUT_OF_SERVICE", "DECOMMISSIONED")
    assert isinstance(data["max_kw"], int) and data["max_kw"] > 0


def assert_charging_session(data: dict):
    _assert_common(data)
    assert data["session_status"] in ("CHARGING", "COMPLETED", "FAULTED")
    assert is_iso8601_timestamp(data.get("started_at", ""))


def assert_event_booking(data: dict):
    _assert_common(data)
    assert data["booking_status"] in (
        "REQUESTED", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED")
    assert isinstance(data["presale_allocation"], int) and data["presale_allocation"] >= 0
    assert isinstance(data["min_staff"], int) and data["min_staff"] >= 0


def assert_money_integer(value, field_name: str):
    """Every monetary figure is an integer number of cents."""
    assert isinstance(value, int), f"{field_name} must be integer cents, got {value!r}"
