"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

CLAIM_STATUSES = {"OPEN", "SETTLED"}
JOB_STATUSES = {"FNOL", "DISPATCHED", "MITIGATION", "MONITORING", "COMPLETED", "CANCELLED"}
DRYING_STATUSES = {"NOT_STARTED", "DRYING", "DRY_STANDARD_MET"}
CHAMBER_STATUSES = {"OPEN", "DRIED", "DECOMMISSIONED"}
EQUIPMENT_STATUSES = {"AVAILABLE", "DEPLOYED"}
EQUIPMENT_KINDS = {"AIR_MOVER", "DEHUMIDIFIER"}
PLACEMENT_STATUSES = {"ACTIVE", "REMOVED"}
ESTIMATE_STATUSES = {"DRAFT", "APPROVED", "SUPERSEDED"}
CONTENTS_STATUSES = {"PACKED_OUT", "STORED", "RETURNED"}
CERTIFICATIONS = {"WRT", "ASD", "AMRT"}


def _assert_versioned_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_claim(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert data["peril"] in {"WATER", "FIRE", "MOLD"}
    assert isinstance(data["coverage_limit_cents"], int)
    assert isinstance(data["deductible_cents"], int)
    assert data["status"] in CLAIM_STATUSES
    assert data["settled_estimate_id"] is None or is_valid_uuid(data["settled_estimate_id"])


def assert_job(data: dict):
    _assert_versioned_common(data)
    assert is_valid_uuid(data["claim_id"]), "claim_id must be a UUID"
    assert isinstance(data["property_address"], str)
    assert data["loss_type"] in {"WATER", "FIRE", "SMOKE"}
    assert data["status"] in JOB_STATUSES
    assert data["drying_status"] in DRYING_STATUSES
    assert isinstance(data["monitoring_day"], int) and data["monitoring_day"] >= 0
    assert isinstance(data["antimicrobial_required"], bool)


def assert_technician(data: dict):
    # Technician is append-only: id + created_at only, no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Technician must NOT carry version"
    assert "updated_at" not in data, "Technician must NOT carry updated_at"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["certification"] in CERTIFICATIONS
    assert isinstance(data["active"], bool)


def assert_chamber(data: dict):
    _assert_versioned_common(data)
    assert is_valid_uuid(data["job_id"]), "job_id must be a UUID"
    assert isinstance(data["room_label"], str) and data["room_label"]
    assert isinstance(data["floor_area_sqft"], int)
    assert data["status"] in CHAMBER_STATUSES
    assert isinstance(data["is_dry"], bool)
    assert isinstance(data["air_movers_required"], int)
    assert isinstance(data["dehumidifiers_required"], int)


def assert_equipment_unit(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["kind"] in EQUIPMENT_KINDS
    assert data["status"] in EQUIPMENT_STATUSES
    assert data["active_placement_id"] is None or is_valid_uuid(data["active_placement_id"])


def assert_placement(data: dict):
    _assert_versioned_common(data)
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["chamber_id"])
    assert is_valid_uuid(data["equipment_unit_id"])
    assert data["kind"] in EQUIPMENT_KINDS
    assert isinstance(data["placed_on_day"], int)
    assert data["status"] in PLACEMENT_STATUSES
    assert isinstance(data["billable_days"], int)


def assert_reading(data: dict):
    # MoistureReading is append-only: id + created_at only.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "MoistureReading must NOT carry version"
    assert "updated_at" not in data, "MoistureReading must NOT carry updated_at"
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["chamber_id"])
    assert isinstance(data["monitoring_day"], int)
    assert isinstance(data["gpp"], (int, float))


def assert_estimate(data: dict):
    _assert_versioned_common(data)
    assert is_valid_uuid(data["job_id"])
    assert isinstance(data["estimated_drying_days"], int)
    assert isinstance(data["line_items"], list)
    assert isinstance(data["scope_lines_total_cents"], int)
    assert isinstance(data["equipment_estimate_cents"], int)
    assert isinstance(data["estimate_total_cents"], int)
    assert isinstance(data["acv_total_cents"], int)
    assert data["status"] in ESTIMATE_STATUSES


def assert_contents(data: dict):
    _assert_versioned_common(data)
    assert is_valid_uuid(data["job_id"])
    assert isinstance(data["description"], str)
    assert isinstance(data["declared_value_cents"], int)
    assert isinstance(data["allocated_value_cents"], int)
    assert data["status"] in CONTENTS_STATUSES


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_pool_conserved(unit: dict):
    """A unit AVAILABLE must have no active placement; a DEPLOYED unit must hold
    exactly one (PRD §3.4)."""
    if unit["status"] == "AVAILABLE":
        assert unit["active_placement_id"] is None, (
            "AVAILABLE unit must have active_placement_id null"
        )
    elif unit["status"] == "DEPLOYED":
        assert unit["active_placement_id"] is not None, (
            "DEPLOYED unit must have an active_placement_id"
        )


def assert_waterfall_conserved(allocated_total: int, claim_limit: int, declared_total: int):
    """sum(allocated) == min(claim_limit, sum(declared)) over included items
    (PRD §3.6)."""
    assert allocated_total == min(claim_limit, declared_total), (
        f"waterfall must conserve: {allocated_total} != min({claim_limit}, {declared_total})"
    )
