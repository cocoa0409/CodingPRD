"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared field-shape helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict, entity: str = "resource"):
    """Every persisted resource carries a server-minted UUID id and created_at;
    almost every one also carries updated_at and an integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_append_only_fields(data: dict, entity: str = "resource"):
    """An append-only record exposes only id and created_at — no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "version" not in data, f"{entity} must not expose a version field"
    assert "updated_at" not in data, f"{entity} must not expose an updated_at field"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_building(data: dict):
    assert_common_fields(data, "Building")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert data["gross_area_sqm"] > 0
    assert data["operating_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["oos_critical_asset_count"], int)
    assert data["oos_critical_asset_count"] >= 0
    assert isinstance(data["open_p1_work_order_count"], int)
    assert data["open_p1_work_order_count"] >= 0


def assert_space(data: dict):
    assert_common_fields(data, "Space")
    assert isinstance(data["space_code"], str) and data["space_code"]
    assert isinstance(data["floor"], int)
    assert data["area_sqm"] > 0
    assert data["space_type"] in ("OFFICE", "LAB", "RETAIL", "COMMON", "PLANT")
    assert data["occupancy_status"] in ("VACANT", "OCCUPIED")
    assert_space_share_invariant(data)


def assert_asset(data: dict):
    assert_common_fields(data, "Asset")
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["category"] in ("HVAC", "ELEVATOR", "FIRE", "ELECTRICAL", "PLUMBING")
    assert data["criticality"] in ("CRITICAL", "STANDARD", "LOW")
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE", "RETIRED")
    assert data["runtime_hours"] >= 0
    assert isinstance(data["failure_count"], int) and data["failure_count"] >= 0
    assert 0 <= data["condition_score"] <= 100, (
        "condition_score must be clamped into the closed range 0 to 100"
    )
    assert_cost_precision(data["condition_score"])


def assert_pm_plan(data: dict):
    assert_common_fields(data, "PMPlan")
    assert data["interval_days"] >= 1
    assert data["grace_days"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RETIRED")
    assert data["compliance_state"] in ("ON_TIME", "DUE", "OVERDUE")


def assert_vendor(data: dict):
    assert_common_fields(data, "Vendor")
    assert data["trade"] in (
        "HVAC", "ELEVATOR", "FIRE", "ELECTRICAL", "PLUMBING", "JANITORIAL", "SECURITY",
    )
    assert data["hourly_rate"] > 0
    assert data["sla_response_minutes"] >= 1
    assert data["sla_resolve_minutes"] >= 1
    assert data["status"] in ("ACTIVE", "PROBATION", "SUSPENDED")
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0
    assert 0 <= data["performance_score"] <= 100
    assert 0 <= data["lifetime_performance_score"] <= 100
    assert isinstance(data["completed_dispatch_count"], int)
    assert_vendor_standing_invariant(data)


def assert_work_order(data: dict):
    assert_common_fields(data, "WorkOrder")
    assert data["wo_type"] in ("CORRECTIVE", "PREVENTIVE", "SOFT_SERVICE")
    assert data["priority"] in ("P1", "P2", "P3", "P4")
    assert isinstance(data["chargeable"], bool)
    assert data["estimated_labor_hours"] >= 0
    assert data["estimated_parts_cost"] >= 0
    assert data["status"] in (
        "NEW", "DISPATCHED", "IN_PROGRESS", "PENDING_QA", "CLOSED", "CANCELLED",
    )
    assert data["billing_status"] in (
        "PENDING", "INVOICED", "SETTLED_CHARGEBACK", "WAIVED",
    )
    assert data["sla_state"] in ("WITHIN", "RESPONSE_BREACHED", "RESOLVE_BREACHED")
    assert isinstance(data["failed_qa_count"], int) and data["failed_qa_count"] >= 0
    assert data["estimated_amount"] >= 0
    assert_cost_precision(data["estimated_amount"])
    if data.get("billable_amount") is not None:
        assert data["billable_amount"] >= 0
        assert_cost_precision(data["billable_amount"])


def assert_dispatch(data: dict):
    assert_common_fields(data, "Dispatch")
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "DECLINED", "COMPLETED", "CANCELLED",
    )
    assert is_iso8601_timestamp(data["dispatched_at"])
    assert 0 <= data["penalty_pct"] <= 0.25, "penalty_pct is capped at 0.25"


def assert_shift(data: dict):
    assert_common_fields(data, "SoftServiceShift")
    assert data["service_type"] in ("JANITORIAL", "SECURITY")
    assert data["planned_headcount"] >= 1
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "MISSED", "CANCELLED",
    )
    assert data["end_at"] > data["start_at"]


def assert_utility_reading(data: dict):
    assert_append_only_fields(data, "UtilityReading")
    assert data["meter_type"] in ("ELECTRIC", "GAS", "WATER")
    assert data["consumption_kwh"] >= 0
    assert data["cost"] >= 0


def assert_lease(data: dict):
    assert_common_fields(data, "Lease")
    assert isinstance(data["tenant_name"], str) and data["tenant_name"]
    assert data["base_rate_per_sqm_month"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED")
    assert data["allocated_area_sqm"] >= 0
    assert_cost_precision(data["allocated_area_sqm"])


def assert_lease_allocation(data: dict):
    assert_common_fields(data, "LeaseAllocation")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["space_id"])
    assert 0 < data["share_pct"] <= 100
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_statement(data: dict):
    assert_common_fields(data, "ChargebackStatement")
    assert is_valid_uuid(data["lease_id"])
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "SETTLED", "VOID")
    for field in ("base_rent", "utility_share", "om_share", "total_amount"):
        assert data[field] >= 0, f"{field} must not be negative"
        assert_cost_precision(data[field])
    assert_statement_total_invariant(data)


def assert_capital_project(data: dict):
    assert_common_fields(data, "CapitalProject")
    assert data["base_cost"] > 0
    assert data["status"] in (
        "PROPOSED", "APPROVED", "REJECTED", "IN_FLIGHT", "CLOSED",
    )
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]
    for field in ("contingency_amount", "budget_amount", "committed_amount",
                  "spent_amount", "remaining_amount"):
        assert_cost_precision(data[field])
    assert_capital_funding_invariant(data)


def assert_building_kpi(data: dict):
    for field in (
        "posture", "energy_intensity_kwh_per_sqm", "total_utility_cost",
        "open_work_order_count", "sla_compliance_pct", "pm_compliance_pct",
        "occupancy_pct",
    ):
        assert field in data, f"KPI dashboard must expose {field}"
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["open_work_order_count"], int)
    for pct in ("sla_compliance_pct", "pm_compliance_pct", "occupancy_pct"):
        assert 0 <= data[pct] <= 100, f"{pct} must be a percentage"


def assert_ops_run_result(data: dict):
    for field in (
        "posture", "created_work_order_ids", "in_progress_shift_ids",
        "missed_shift_ids", "retired_asset_ids", "expired_lease_ids",
        "closed_project_ids",
    ):
        assert field in data, f"the epoch run must report {field}"
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")


# ---------------------------------------------------------------------------
# Domain invariants (PRD §2.10 Conserved Quantities)
# ---------------------------------------------------------------------------
def assert_space_share_invariant(space: dict):
    """allocated_share_pct and free_share_pct always sum to exactly 100."""
    total = space["allocated_share_pct"] + space["free_share_pct"]
    assert total == pytest.approx(100, abs=0.01), (
        f"allocated_share_pct ({space['allocated_share_pct']}) + free_share_pct "
        f"({space['free_share_pct']}) must equal 100, got {total}"
    )
    expected_status = "OCCUPIED" if space["allocated_share_pct"] > 0 else "VACANT"
    assert space["occupancy_status"] == expected_status, (
        f"occupancy_status must be {expected_status} when allocated_share_pct is "
        f"{space['allocated_share_pct']}"
    )


def assert_capital_funding_invariant(project: dict):
    """budget_amount - committed_amount - spent_amount always equals remaining_amount."""
    expected = (
        project["budget_amount"] - project["committed_amount"] - project["spent_amount"]
    )
    assert project["remaining_amount"] == pytest.approx(expected, abs=0.01), (
        f"remaining_amount must be budget ({project['budget_amount']}) less committed "
        f"({project['committed_amount']}) less spent ({project['spent_amount']}) = "
        f"{expected}, got {project['remaining_amount']}"
    )


def assert_statement_total_invariant(statement: dict):
    """total_amount is the sum of the three already-rounded money lines."""
    expected = (
        statement["base_rent"] + statement["utility_share"] + statement["om_share"]
    )
    assert statement["total_amount"] == pytest.approx(expected, abs=0.01), (
        f"total_amount must be base_rent + utility_share + om_share = {expected}, "
        f"got {statement['total_amount']}"
    )


def assert_vendor_standing_invariant(vendor: dict):
    """The strike ladder: exactly 2 strikes is PROBATION, 3 or more is SUSPENDED."""
    strikes = vendor["strike_count"]
    if strikes >= 3:
        expected = "SUSPENDED"
    elif strikes == 2:
        expected = "PROBATION"
    else:
        expected = "ACTIVE"
    assert vendor["status"] == expected, (
        f"a vendor on {strikes} strikes must be {expected}, got {vendor['status']}"
    )
