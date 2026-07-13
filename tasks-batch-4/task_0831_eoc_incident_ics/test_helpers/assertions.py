"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §2.9).

Each assert_{entity}() validates the common system-managed fields (id,
created_at, version) plus the entity's own fields. Invariant checkers
enforce the conserved-quantity guarantees the PRD states hold at all times.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["hazard_type"] in [
        "FLOOD", "WILDFIRE", "HURRICANE", "EARTHQUAKE", "HAZMAT", "PUBLIC_HEALTH",
    ]
    assert data["declaration_category"] in ["EMERGENCY", "MAJOR_DISASTER"]
    assert data["op_status"] in ["MONITORING", "ACTIVATED", "DEMOBILIZING", "CLOSED"]
    assert data["activation_level"] in ["LEVEL_1", "LEVEL_2", "LEVEL_3"]
    assert data["declaration_status"] in ["INELIGIBLE", "ELIGIBLE"]


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_resource_pool(data: dict):
    _assert_common(data)
    assert data["resource_type"] in ["PERSONNEL", "VEHICLE", "EQUIPMENT", "SUPPLY"]
    assert isinstance(data["total_units"], int)
    assert_pool_conserved(data)


def assert_resource_request(data: dict):
    _assert_common(data)
    assert data["resource_type"] in ["PERSONNEL", "VEHICLE", "EQUIPMENT", "SUPPLY"]
    assert data["priority"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "NEEDS_INFO", "SOURCED", "FILLED", "DENIED", "DEMOBILIZED",
    ]


def assert_iap(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "PUBLISHED", "CLOSED"]


def assert_task(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLANNED", "ASSIGNED", "COMPLETED", "CANCELLED"]


def assert_shelter(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLANNED", "OPEN", "CLOSED"]
    assert isinstance(data["capacity"], int)
    assert_shelter_capacity_invariant(data)


def assert_mutual_aid_request(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "REQUESTED", "OFFERED", "COUNTERED", "ACCEPTED", "DECLINED", "WITHDRAWN",
    ]


def assert_damage_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "VALIDATED", "REJECTED"]
    assert data["infrastructure_category"] in [
        "CAT_A_DEBRIS", "CAT_B_PROTECTIVE", "CAT_C_ROADS", "CAT_E_BUILDINGS", "CAT_G_PARKS",
    ]


def assert_cost_record(data: dict):
    _assert_common(data)
    assert data["category"] in ["LABOR", "EQUIPMENT", "MATERIALS", "CONTRACT"]
    assert data["status"] in ["ESTIMATED", "ACTUAL", "VOID"]
    assert isinstance(data["eligible"], bool)


# ─── Domain invariant checkers (PRD §2.8, §2.9) ──────────────────────
def assert_pool_conserved(pool: dict):
    """PRD §2.8: total_units == units_available + units_reserved + units_committed."""
    assert (
        pool["total_units"]
        == pool["units_available"] + pool["units_reserved"] + pool["units_committed"]
    ), (
        f"Pool conservation violated: total={pool['total_units']} != "
        f"avail={pool['units_available']} + reserved={pool['units_reserved']} + "
        f"committed={pool['units_committed']}"
    )


def assert_shelter_capacity_invariant(shelter: dict):
    """PRD §3.5: current_occupancy + reserved_occupancy must not exceed capacity."""
    assert shelter["current_occupancy"] >= 0
    assert shelter["reserved_occupancy"] >= 0
    assert shelter["current_occupancy"] + shelter["reserved_occupancy"] <= shelter["capacity"]


def assert_incident_cost_ledger(incident: dict):
    """PRD §2.9: monetary rollups carry two-decimal precision."""
    assert_cost_precision(incident["total_committed_cost"])
    assert_cost_precision(incident["total_actual_cost"])
    assert_cost_precision(incident["federal_share_estimated"])
    assert_cost_precision(incident["federal_share_actual"])
