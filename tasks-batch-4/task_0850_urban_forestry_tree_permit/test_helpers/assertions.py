"""Entity assertions and domain invariant checkers (Urban Forestry & Tree Permit API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for mutable (common_fields) resources."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["target_canopy_pct"], (int, float))
    assert isinstance(data["area_sqm"], (int, float)) and data["area_sqm"] > 0
    assert isinstance(data["live_canopy_sqm"], (int, float)) and data["live_canopy_sqm"] >= 0
    assert isinstance(data["current_canopy_pct"], (int, float)) and data["current_canopy_pct"] >= 0
    assert data["canopy_status"] in ("MEETS", "DEFICIT")
    assert isinstance(data["high_risk_tree_count"], int) and data["high_risk_tree_count"] >= 0
    assert isinstance(data["tree_count"], int) and data["tree_count"] >= 0


def assert_species(data: dict):
    # common_fields: false -> only id + created_at; NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Species is immutable config: it must not carry updated_at"
    assert "version" not in data, "Species is immutable config: it must not carry version"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["is_protected_species"], bool)
    assert isinstance(data["is_native"], bool)
    assert isinstance(data["mature_canopy_sqm"], (int, float)) and data["mature_canopy_sqm"] >= 0


def assert_tree(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["species_id"])
    assert isinstance(data["dbh_inches"], (int, float)) and data["dbh_inches"] > 0
    assert data["condition_class"] in ("GOOD", "FAIR", "POOR", "DEAD")
    assert isinstance(data["is_protected"], bool)
    assert data["health_status"] in ("HEALTHY", "DECLINING", "HAZARD", "REMOVED")
    assert data["risk_rating"] in ("NONE", "LOW", "MODERATE", "HIGH", "SEVERE")


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tree_id"])
    assert data["inspection_type"] in ("ROUTINE", "RISK", "POST_STORM")
    assert data["status"] in ("DRAFT", "FINALIZED", "DISPUTED")
    assert isinstance(data["provisional_risk_score"], int)
    assert data["provisional_risk_rating"] in ("LOW", "MODERATE", "HIGH", "SEVERE")


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tree_id"])
    assert data["permit_type"] in ("REMOVAL", "PRUNING")
    assert data["status"] in (
        "DRAFT", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED",
        "DENIED", "ISSUED", "CLOSED", "REVOKED",
    )
    assert isinstance(data["required_replacement_count"], int)
    assert isinstance(data["mitigation_fee_cents"], int)
    assert isinstance(data["fee_paid"], bool)


def assert_contractor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["is_certified_arborist"], bool)


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tree_id"])
    assert is_valid_uuid(data["contractor_id"])
    assert data["work_type"] in ("REMOVAL", "PRUNING", "EMERGENCY_REMOVAL")
    assert data["status"] in ("CREATED", "IN_PROGRESS", "COMPLETED", "ABORTED")


def assert_dig_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["work_order_id"])
    assert data["status"] in ("REQUESTED", "VALID", "EXPIRED")


def assert_storm_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["affected_zone_id"])
    assert data["severity"] in ("MINOR", "MAJOR", "SEVERE")
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_replacement_planting(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["permit_id"])
    assert data["status"] in ("REQUIRED", "PLANTED", "ESTABLISHED")
    assert isinstance(data["sequence_index"], int)
