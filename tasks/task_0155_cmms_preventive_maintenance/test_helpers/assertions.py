"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape the PRD promises that entity returns.
MeterReading is the immutable entity (PRD §2.4): no updated_at, no version.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)
    assert isinstance(data["maintenance_budget_cents"], int)
    assert isinstance(data["budget_spent_cents"], int)
    assert data["budget_spent_cents"] >= 0, "budget_spent_cents must be >= 0"


def assert_spare_part(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["reorder_point"], int)


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["skill_level"] in ("JUNIOR", "SENIOR", "MASTER")
    assert data["weekly_capacity_hours"] > 0
    assert data["backlog_hours"] >= 0


def assert_asset(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["criticality"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in ("OPERATIONAL", "DOWN", "RETIRED")
    assert data["meter_unit"] in ("HOURS", "CYCLES", "KM")
    assert data["meter_reading"] >= 0
    assert isinstance(data["acquisition_cost_cents"], int)
    assert data["mtbf_hours"] >= 0
    assert data["mttr_hours"] >= 0


def assert_pm_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be a valid UUID"
    assert data["trigger_type"] in ("METER", "CALENDAR")
    assert data["estimated_labor_hours"] > 0
    assert data["severity"] in ("ROUTINE", "MAJOR", "OVERHAUL")
    assert isinstance(data["active"], bool)


def assert_meter_reading(data: dict):
    """MeterReading is immutable: id + created_at only, NO version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be a valid UUID"
    assert data["value"] >= 0
    assert isinstance(data["triggered_pm"], bool)


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be a valid UUID"
    assert data["wo_type"] in ("PREVENTIVE", "CORRECTIVE")
    assert data["severity"] in ("ROUTINE", "MAJOR", "OVERHAUL")
    assert data["execution_status"] in (
        "DRAFT", "UNASSIGNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD", "CLOSED", "CANCELLED"
    )
    assert data["parts_status"] in ("NONE", "RESERVED", "COMMITTED", "RELEASED")
    assert data["priority_score"] >= 0
    assert data["estimated_labor_hours"] > 0
    assert isinstance(data["actual_cost_cents"], int)


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a valid UUID"
    assert is_valid_uuid(data.get("spare_part_id", "")), "spare_part_id must be a valid UUID"
    assert isinstance(data["qty"], int) and data["qty"] > 0
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED")
    assert isinstance(data["committed_cost_cents"], int)


def assert_downtime_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be a valid UUID"
    assert data["reason_code"] in (
        "MECHANICAL_FAILURE", "ELECTRICAL_FAILURE", "OPERATOR_ERROR", "PLANNED_PM", "IDLE"
    )
    assert is_iso8601_timestamp(data.get("started_at", "")), "started_at must be ISO 8601"
    assert data["status"] in ("OPEN", "RESOLVED")
    assert data["duration_hours"] >= 0


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be a valid UUID"
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a valid UUID"
    assert data["claim_type"] in ("REPLACEMENT", "REPAIR")
    assert isinstance(data["claimed_cost_cents"], int)
    assert isinstance(data["payable_cost_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")


def assert_available_units(part: dict, expected: int):
    """Available units = on_hand_qty - reserved_qty (PRD §3.1)."""
    available = part["on_hand_qty"] - part["reserved_qty"]
    assert available == expected, (
        f"Expected available units {expected}, got {available} "
        f"(on_hand {part['on_hand_qty']} - reserved {part['reserved_qty']})"
    )
