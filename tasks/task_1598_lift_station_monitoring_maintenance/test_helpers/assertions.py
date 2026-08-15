"""Entity assertions and domain invariant checkers (PRD §2.4/§3)."""
from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"not an ISO 8601 UTC timestamp: {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected_iso: str):
    """Two ISO 8601 UTC strings denote the same instant (fractional-digit
    representation may differ between serializer and expectation)."""
    assert parse_ts(actual) == parse_ts(expected_iso), (
        f"expected instant {expected_iso}, got {actual}"
    )


def hours_between(start_iso: str, end_iso: str) -> float:
    return (parse_ts(end_iso) - parse_ts(start_iso)).total_seconds() / 3600.0

POSTURES = ["NORMAL", "DEGRADED", "EMERGENCY", "FROZEN"]
PUMP_STATUSES = ["IN_SERVICE", "STANDBY", "OUT_OF_SERVICE", "REBUILD"]
ALARM_CLASSES = ["CRITICAL", "MAJOR", "MINOR", "INFO"]
TICKET_STATUSES = ["OPEN", "ACKED", "DISPATCHED", "ON_SCENE", "CLEARED", "CANCELLED"]
READING_SOURCES = ["SCADA", "MANUAL", "BACKFILL"]
REBUILD_STATUSES = ["OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
CLEANING_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "OVERDUE"]
GEN_TEST_KINDS = ["NO_LOAD", "LOAD_BANK", "TRANSFER_SWITCH"]
GEN_TEST_STATUSES = ["SCHEDULED", "RUNNING", "PASSED", "FAILED", "ABORTED", "OVERDUE"]
SSO_STATUSES = [
    "OPEN", "CONTAINED", "REPORT_DRAFT", "REPORT_SUBMITTED", "REPORT_ACCEPTED", "CLOSED",
]
SSO_CAUSES = [
    "GREASE_BLOCKAGE", "DEBRIS", "POWER_FAILURE", "PUMP_FAILURE",
    "INFLOW_INFILTRATION", "VANDALISM", "UNKNOWN",
]
PERMIT_STATUSES = ["DRAFT", "ISSUED", "ACTIVE", "SUSPENDED", "CLOSED", "CANCELLED"]
PLAN_STATUSES = ["DRAFT", "RANKED", "APPROVED", "LOCKED"]
PROJECT_STATUSES = ["PROPOSED", "RANKED", "APPROVED", "REJECTED", "DEFERRED", "CANCELLED"]
SPARE_STATUSES = ["AVAILABLE", "RESERVED", "DEPLOYED", "REBUILD", "RETIRED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_station(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert isinstance(data["service_zone"], str) and data["service_zone"]
    assert isinstance(data["design_capacity_gpm"], int)
    assert isinstance(data["pump_count"], int)
    assert isinstance(data["has_backup_generator"], bool)
    assert isinstance(data["wet_well_volume_gal"], int)
    assert data["operational_posture"] in POSTURES
    assert isinstance(data["firm_capacity_available_gpm"], int)


def assert_pump(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["station_id"], str) and data["station_id"]
    assert isinstance(data["position_index"], int)
    assert isinstance(data["rated_gpm"], int)
    assert data["status"] in PUMP_STATUSES
    assert isinstance(data["cumulative_runtime_hours"], (int, float))
    assert isinstance(data["runtime_since_rebuild_hours"], (int, float))
    assert isinstance(data["rebuild_count"], int)


def assert_runtime_reading(data: dict):
    """Append-only telemetry: only id + created_at from the common set (PRD §2.4);
    updated_at and version must be absent from the serialized form."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "runtime readings must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "runtime readings must not carry version (PRD §2.4)"
    assert isinstance(data["pump_id"], str) and data["pump_id"]
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"
    assert isinstance(data["run_hours_delta"], (int, float))
    assert isinstance(data["starts_count"], int)
    assert data["source"] in READING_SOURCES


def assert_alarm_ticket(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["station_id"], str) and data["station_id"]
    assert data["alarm_class"] in ALARM_CLASSES
    assert isinstance(data["alarm_code"], str) and data["alarm_code"]
    assert is_iso8601_timestamp(data.get("raised_at", "")), "raised_at must be ISO 8601"
    assert data["status"] in TICKET_STATUSES
    assert isinstance(data["is_sso_related"], bool)


def assert_operator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["certifications"], list)
    assert isinstance(data["home_zone"], str) and data["home_zone"]
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["active_ticket_count"], int)
    assert isinstance(data["consecutive_callouts_24h"], int)


def assert_pump_rebuild(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pump_id"], str) and data["pump_id"]
    assert isinstance(data["work_order_ref"], str) and data["work_order_ref"]
    assert is_iso8601_timestamp(data.get("started_at", "")), "started_at must be ISO 8601"
    assert data["status"] in REBUILD_STATUSES
    assert_cost_precision(float(data["cost_usd"]))


def assert_cleaning(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["station_id"], str) and data["station_id"]
    assert is_iso8601_timestamp(data.get("scheduled_for", "")), "scheduled_for must be ISO 8601"
    assert data["status"] in CLEANING_STATUSES
    assert isinstance(data["grease_depth_inches_pre"], (int, float))
    assert isinstance(data["crew_lead_operator_id"], str) and data["crew_lead_operator_id"]
    assert isinstance(data["requires_confined_space_entry"], bool)


def assert_generator_test(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["station_id"], str) and data["station_id"]
    assert is_iso8601_timestamp(data.get("scheduled_for", "")), "scheduled_for must be ISO 8601"
    assert data["test_kind"] in GEN_TEST_KINDS
    assert data["status"] in GEN_TEST_STATUSES
    assert isinstance(data["load_percent"], (int, float))


def assert_sso_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["station_id"], str) and data["station_id"]
    assert is_iso8601_timestamp(data.get("started_at", "")), "started_at must be ISO 8601"
    assert data["cause_code"] in SSO_CAUSES
    assert data["status"] in SSO_STATUSES
    assert isinstance(data["reached_surface_water"], bool)


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["station_id"], str) and data["station_id"]
    assert isinstance(data["work_description"], str) and data["work_description"]
    assert isinstance(data["authorized_entrant_id"], str) and data["authorized_entrant_id"]
    assert isinstance(data["attendant_operator_id"], str) and data["attendant_operator_id"]
    assert isinstance(data["entry_supervisor_id"], str) and data["entry_supervisor_id"]
    assert data["status"] in PERMIT_STATUSES
    assert isinstance(data["gas_test_passed"], bool)


def assert_capital_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_year"], int)
    assert data["status"] in PLAN_STATUSES
    assert_cost_precision(float(data["budget_total_usd"]))
    assert_cost_precision(float(data["budget_allocated_usd"]))
    assert_cost_precision(float(data["budget_remaining_usd"]))


def assert_capital_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str) and data["plan_id"]
    assert isinstance(data["station_id"], str) and data["station_id"]
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert_cost_precision(float(data["estimated_cost_usd"]))
    assert data["status"] in PROJECT_STATUSES
    assert isinstance(data["consequence_of_failure"], int)
    assert isinstance(data["likelihood_of_failure"], int)
    assert 1 <= data["consequence_of_failure"] <= 10
    assert 1 <= data["likelihood_of_failure"] <= 10


def assert_spare_pump(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert isinstance(data["rated_gpm"], int)
    assert isinstance(data["compatible_zone"], str) and data["compatible_zone"]
    assert data["status"] in SPARE_STATUSES


def assert_station_invariants(data: dict):
    """Station-level invariants that hold on every read (PRD §2.7/§3.2)."""
    assert data["firm_capacity_available_gpm"] >= 0, "firm capacity is never negative"
    assert data["operational_posture"] in POSTURES


def assert_plan_budget_conservation(plan: dict):
    """Budget conservation invariant (PRD §3.10): remaining is total minus
    allocated, floored at 0.00 for reporting."""
    total = float(plan["budget_total_usd"])
    allocated = float(plan["budget_allocated_usd"])
    remaining = float(plan["budget_remaining_usd"])
    assert remaining == pytest.approx(max(0.0, total - allocated), abs=0.01), (
        f"budget conservation violated: allocated={allocated} remaining={remaining} total={total}"
    )
