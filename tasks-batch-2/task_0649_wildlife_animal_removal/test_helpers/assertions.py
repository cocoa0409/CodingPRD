"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields present on every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_species_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["common_name"], str) and len(data["common_name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["is_regulated"], bool)
    assert isinstance(data["base_trap_fee_cents"], int)


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["license_tier"] in ("BASIC", "CERTIFIED")
    assert isinstance(data["kit_trap_capacity"], int)
    assert isinstance(data["traps_deployed"], int)
    assert isinstance(data["traps_available"], int)
    assert_technician_kit_invariant(data)


def assert_technician_kit_invariant(data: dict):
    """Conserved kit pool: traps_deployed + traps_available == kit_trap_capacity,
    traps_available never negative (PRD §2.8)."""
    assert data["traps_available"] >= 0, "traps_available must never be negative"
    assert data["traps_deployed"] + data["traps_available"] == data["kit_trap_capacity"], (
        "traps_deployed + traps_available must equal kit_trap_capacity"
    )


def assert_property(data: dict):
    _assert_common(data)
    assert data["posture"] in ("OPEN", "ACTIVE_REMEDIATION", "REGULATORY_HOLD")


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "COMPLETED", "CANCELLED")
    assert isinstance(data["is_emergency"], bool)
    assert isinstance(data["detected_individual_count"], int)


def assert_entry_point(data: dict):
    _assert_common(data)
    assert data["severity"] in ("MINOR", "MODERATE", "MAJOR")
    assert data["seal_status"] in ("OPEN", "SEALED")
    assert isinstance(data["estimated_individuals"], int)


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SENT", "REVISION_REQUESTED", "ACCEPTED", "DECLINED", "SUPERSEDED",
    )
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)
    assert isinstance(data["emergency_flag"], bool)


def assert_quote_line_item(data: dict):
    _assert_common(data)
    assert data["line_type"] in ("TRAP", "EXCLUSION")
    assert isinstance(data["quantity"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["performed"], bool)


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["lifecycle"] in ("OPEN", "CLOSED", "CANCELLED")
    assert data["removal_status"] in ("PENDING", "TRAPPING", "CLEARED")
    assert data["exclusion_status"] in ("PENDING", "SEALING", "SEALED")
    assert isinstance(data["net_charged_cents"], int)
    assert isinstance(data["initial_risk_score"], (int, float))
    assert isinstance(data["residual_risk_score"], (int, float))


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_trap_placement(data: dict):
    _assert_common(data)
    assert data["status"] in ("SET", "SPENT", "EMPTY", "CANCELLED")


def assert_capture_event(data: dict):
    _assert_common(data)
    assert data["disposition"] == "RELOCATED"
    assert isinstance(data["release_distance_miles"], (int, float))


def assert_exclusion_repair(data: dict):
    _assert_common(data)
    assert data["status"] in ("STARTED", "COMPLETED")
    assert isinstance(data["sanitation_included"], bool)


def assert_monitoring_visit(data: dict):
    _assert_common(data)
    assert isinstance(data["traps_reset"], int)


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "ACCEPTED", "REJECTED")
