"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_venue(data: dict):
    _assert_common(data)
    assert data["union_ruleset"] in ["IATSE", "TEAMSTERS", "NON_UNION"]
    assert data["max_point_capacity_kg"] > 0
    assert data["bay_aggregate_limit_kg"] > 0
    assert data["house_power_amps_per_phase"] > 0
    assert data["dock_doors"] >= 1


def assert_technician(data: dict):
    _assert_common(data)
    assert data["classification"] in ["LIGHTING_TECH", "RIGGER", "STAGEHAND"]
    assert data["hourly_rate_cents"] > 0


def assert_production(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "PLANNING", "READY_FOR_LOADIN", "LOAD_IN", "SHOW_READY",
        "SHOW_COMPLETE", "LOAD_OUT", "CLOSED", "SETTLED", "CANCELLED",
    ]
    assert data["posture"] in ["BLOCKED", "PARTIAL", "READY"]


def assert_plot(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["total_factored_load_kg"] >= 0


def assert_rigging_point(data: dict):
    _assert_common(data)
    assert data["status"] in ["RESERVED", "UNDER_REVIEW", "APPROVED", "REJECTED", "RELEASED"]
    assert data["hang_type"] in ["STRAIGHT", "BRIDLE", "DEAD_HANG"]
    assert data["factored_load_kg"] > 0
    assert data["utilization"] > 0


def assert_asset(data: dict):
    _assert_common(data)
    assert data["status"] in ["AVAILABLE", "RESERVED", "PREPPED", "DEPLOYED", "DAMAGED", "LOST", "RETIRED"]
    assert data["asset_class"] in [
        "MOVING_LIGHT", "LED_PANEL", "TRUSS_12IN", "CHAIN_MOTOR",
        "DISTRO_BOX", "CABLE_FEEDER", "CONSOLE", "FOLLOWSPOT",
    ]
    assert data["weight_kg"] > 0


def assert_pull_list_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "RESERVED", "PREPPED", "OUT", "RETURNED", "DAMAGED", "LOST", "CANCELLED"]


def assert_crew_call(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "PUBLISHED", "CONFIRMED", "COMPLETED", "CANCELLED"]
    assert data["department"] in ["LIGHTING", "RIGGING", "STAGEHANDS"]


def assert_crew_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ASSIGNED", "CONFIRMED", "WORKED", "NO_SHOW", "RECONCILED", "CANCELLED"]


def assert_power_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]


def assert_truck(data: dict):
    _assert_common(data)
    assert data["capacity_kg"] > 0


def assert_load_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLANNED", "CONFIRMED", "AUTHORIZED", "COMPLETE", "CANCELLED"]
    assert data["direction"] in ["LOAD_IN", "LOAD_OUT"]


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "CANCELLED"]
    assert data["inspection_type"] in ["RIGGING", "ELECTRICAL", "FINAL"]
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1


def assert_damage_report(data: dict):
    _assert_common(data)
    assert data["status"] in ["FILED", "ASSESSED", "CHARGED", "WAIVED"]
    assert data["report_type"] in ["DAMAGE", "LOSS"]


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ISSUED", "DISPUTED", "RESOLVED", "PAID"]
    for field in ("labor_total_cents", "equipment_total_cents", "damage_total_cents",
                  "provisional_damage_cents", "grand_total_cents", "provisional_grand_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_settlement_invariants(data: dict):
    """PRD §3.9: the provisional grand total is labor + equipment + provisional damage."""
    assert data["provisional_grand_total_cents"] == (
        data["labor_total_cents"] + data["equipment_total_cents"] + data["provisional_damage_cents"]
    ), "provisional grand must equal labor + equipment + provisional damage"
