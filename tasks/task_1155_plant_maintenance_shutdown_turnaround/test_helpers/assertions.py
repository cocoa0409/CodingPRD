"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_turnaround(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("plant_unit"), str)
    assert data["status"] in [
        "PLANNING", "SCOPE_FROZEN", "MOBILIZATION", "EXECUTION",
        "STARTUP", "HANDED_OVER", "CANCELLED",
    ]
    assert data["cost_posture"] in ["WITHIN_BUDGET", "AT_RISK", "OVERRUN"]
    assert isinstance(data["committed_cost_cents"], int)
    assert isinstance(data["reported_cost_cents"], int)
    assert isinstance(data["schedule_run_index"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_work_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in [
        "PROPOSED", "FROZEN", "DEFERRED", "SCHEDULED", "IN_PROGRESS",
        "ON_HOLD", "COMPLETE", "REOPENED", "VERIFIED", "CANCELLED",
    ]
    assert data["work_type"] in ["CORRECTIVE", "PREVENTIVE", "INSPECTION", "DISCOVERY_ADDENDUM"]
    assert data["risk_class"] in ["A", "B", "C"]
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_work_item_dependency(data: dict):
    # Append-only edge: only id + created_at among common fields
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data.get("predecessor_work_item_id", "")), \
        "predecessor_work_item_id must be a UUID"
    assert is_valid_uuid(data.get("successor_work_item_id", "")), \
        "successor_work_item_id must be a UUID"


def assert_contractor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["mobilization_status"] in ["INVITED", "MOBILIZING", "MOBILIZED", "DEMOBILIZED"]
    assert isinstance(data["headcount_cap"], int) and data["headcount_cap"] >= 1
    assert isinstance(data["badged_headcount"], int) and data["badged_headcount"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_worker(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["badge_status"] in ["REGISTERED", "VETTED", "BADGED", "SUSPENDED", "DEBADGED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_shift(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["shift_type"] in ["DAY", "NIGHT"]
    assert data["status"] in ["PLANNED", "LOCKED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["planned_headcount"], int) and data["planned_headcount"] >= 1
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ASSIGNED", "COMPLETED", "NO_SHOW", "CANCELLED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_permit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["permit_type"] in ["COLD_WORK", "HOT_WORK", "CONFINED_SPACE"]
    assert data["hazard_class"] in ["LOW", "HIGH"]
    assert data["status"] in [
        "REQUESTED", "ISSUED", "ACTIVE", "SUSPENDED", "CLOSED", "REVOKED", "EXPIRED",
    ]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_isolation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["isolation_mode"] in ["EXCLUSIVE", "SHARED"]
    assert data["status"] in ["PLANNED", "ISOLATED", "VERIFIED", "DEISOLATED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_discovery(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["REPORTED", "TRIAGED", "AUTHORIZED", "REJECTED"]
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_laydown_area(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["capacity_sqm"], int) and data["capacity_sqm"] > 0
    assert isinstance(data["occupied_sqm"], int) and data["occupied_sqm"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_reservation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["RESERVED", "STAGED", "RELEASED", "CANCELLED"]
    assert isinstance(data["area_sqm"], int) and data["area_sqm"] > 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_daily_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "VOIDED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_punch_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["category"] in ["A", "B"]
    assert data["status"] in ["OPEN", "READY", "VERIFIED", "REOPENED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_turnaround_cost_invariants(data: dict):
    """Turnaround money invariants that must hold after any operation."""
    assert data["committed_cost_cents"] >= 0
    assert data["reported_cost_cents"] >= 0
    assert data["critical_path_slip_hours"] >= 0
    assert data["cost_posture"] in ["WITHIN_BUDGET", "AT_RISK", "OVERRUN"]


def assert_laydown_occupancy_invariant(area: dict, reservations: list):
    """occupied_sqm must equal the sum of area_sqm over reservations in {RESERVED, STAGED}."""
    live = [r for r in reservations if r.get("status") in ("RESERVED", "STAGED")]
    expected = sum(r["area_sqm"] for r in live)
    assert area["occupied_sqm"] == expected, (
        f"occupied_sqm invariant violated: {area['occupied_sqm']} != {expected}"
    )
    assert area["occupied_sqm"] >= 0


def assert_worker_fatigue_invariants(worker: dict):
    assert worker["ledger_hours"] >= 0
    assert worker["fatigue_penalty_score"] >= 0
    assert worker["total_shift_hours"] >= 0
