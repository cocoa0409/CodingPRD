"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits."""
    assert isinstance(value, str), f"expected ISO timestamp string, got {value!r}"
    text = value.strip()
    assert is_iso8601_timestamp(text), f"Not a valid ISO 8601 UTC timestamp: {value!r}"
    if "." in text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def assert_same_instant(actual: str, expected_iso: str):
    """Two timestamp renderings denote the same UTC instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["capability"] in ("TECHNICIAN", "SUPERVISOR")
    assert isinstance(data["base_hourly_rate_cents"], int)
    assert isinstance(data["on_call_differential_bp"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["callback_minutes_168h"], int)
    assert data.get("fatigue_block_until") is None or is_iso8601_timestamp(
        data["fatigue_block_until"]
    )


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["building_code"], str) and data["building_code"]
    assert data["habitability_status"] in ("HABITABLE", "UNINHABITABLE")


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["trade"] in (
        "PLUMBING",
        "HVAC",
        "ELECTRICAL",
        "GENERAL",
        "RESTORATION",
    )
    assert isinstance(data["per_incident_limit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_rotation_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("technician_id", ""))
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in ("PUBLISHED", "ACTIVE", "COMPLETED", "CANCELLED")
    assert isinstance(data["needs_coverage"], bool)


def assert_call_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["category"] in (
        "GAS_LEAK",
        "FLOOD",
        "NO_HEAT",
        "NO_POWER",
        "LOCKOUT",
        "LEAK_MINOR",
        "APPLIANCE",
        "OTHER",
    )
    assert data["status"] in (
        "RECEIVED",
        "TRIAGED",
        "DISPATCHED",
        "ESCALATED",
        "ON_SCENE",
        "MITIGATED",
        "CLOSED",
        "DEFERRED",
    )
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert isinstance(data["escalation_level"], int)
    assert isinstance(data["unit_declared_uninhabitable"], bool)


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("call_ticket_id", ""))
    assert data["priority"] in ("EMERGENCY_FOLLOWUP", "DEFERRED", "STANDARD")
    assert data["status"] in (
        "OPEN",
        "ASSIGNED",
        "IN_PROGRESS",
        "ON_HOLD",
        "COMPLETED",
        "REOPENED",
        "VERIFIED",
        "CANCELLED",
    )


def assert_vendor_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("call_ticket_id", ""))
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in (
        "PROPOSED",
        "AUTHORIZED",
        "REJECTED",
        "VOIDED",
        "INVOICED",
        "PAID",
    )


def assert_relocation_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("call_ticket_id", ""))
    assert data["status"] in ("PROPOSED", "APPROVED", "ACTIVE", "ENDED", "REJECTED")
    assert isinstance(data["planned_nights"], int) and data["planned_nights"] >= 1
    assert isinstance(data["est_cost_cents"], int)
    assert isinstance(data["nightly_rate_cents"], int)


def assert_incident_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("call_ticket_id", ""))
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "RETURNED",
        "FINALIZED",
    )
    assert isinstance(data["estimated_damage_cents"], int)


def assert_pay_period(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["status"] in ("OPEN", "CLOSED")


def assert_pay_statement(data: dict):
    """PayStatement carries only id + created_at plus its payload (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "PayStatement must not carry updated_at"
    assert "version" not in data, "PayStatement must not carry version"
    assert is_valid_uuid(data.get("pay_period_id", ""))
    assert is_valid_uuid(data.get("technician_id", ""))
    for field in (
        "standby_minutes_total",
        "standby_pay_final_cents",
        "callback_minutes_total",
        "callback_pay_final_cents",
        "total_pay_cents",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert (
        data["total_pay_cents"]
        == data["standby_pay_final_cents"] + data["callback_pay_final_cents"]
    ), "total_pay_cents must equal standby final plus callback final"
