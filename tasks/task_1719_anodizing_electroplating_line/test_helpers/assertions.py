"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert data["priority_tier"] in ("STANDARD", "PREFERRED")
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_fixture(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fixture_code"], str) and len(data["fixture_code"]) > 0
    assert data["routing_mode"] in ("RACK", "BARREL")
    assert data["capacity_dm2"] > 0
    assert data["purchase_cost_cents"] >= 0
    assert data["rated_uses"] >= 1
    assert isinstance(data["amortization_cents_per_use"], int)


def assert_alloy_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["alloy_code"], str) and len(data["alloy_code"]) > 0
    assert data["process_type"] in ("ANODIZE", "PLATE")
    assert data["chemistry_family"] in (
        "SULFURIC", "CHROMIC", "NICKEL", "ZINC", "COPPER", "CYANIDE",
    )
    assert data["compatibility"] in ("COMPATIBLE", "CONDITIONAL", "INCOMPATIBLE")


def assert_bath(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bath_code"], str) and len(data["bath_code"]) > 0
    assert data["process_type"] in ("ANODIZE", "PLATE")
    assert data["chemistry_family"] in (
        "SULFURIC", "CHROMIC", "NICKEL", "ZINC", "COPPER", "CYANIDE",
    )
    assert isinstance(data["routing_modes_supported"], list)
    assert len(data["routing_modes_supported"]) >= 1
    assert data["volume_liters"] > 0
    assert data["target_concentration_g_l"] > 0
    assert data["status"] in ("ACTIVE", "QUARANTINED", "EXHAUSTED", "DUMPED", "DECOMMISSIONED")
    assert data["amp_hour_used"] >= 0
    assert data["amp_hour_reserved"] >= 0
    assert isinstance(data["dose_verification_pending"], bool)


def assert_titration(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["bath_id"], str)
    assert data["titrant_volume_ml"] > 0
    assert data["titrant_normality"] > 0
    assert data["sample_volume_ml"] > 0
    assert isinstance(data["measured_concentration_g_l"], (int, float))


def assert_dose_event(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["bath_id"], str)
    assert isinstance(data["chemical_code"], str) and len(data["chemical_code"]) > 0
    assert data["quantity_g"] > 0
    assert isinstance(data["resulting_concentration_g_l"], (int, float))


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["part_number"], str)
    assert data["process_type"] in ("ANODIZE", "PLATE")
    assert data["routing_mode"] in ("RACK", "BARREL")
    assert data["part_count"] >= 1
    assert data["surface_area_dm2_per_part"] > 0
    assert data["surface_area_total_dm2"] > 0
    assert data["status"] in (
        "RECEIVED", "READY_FOR_ROUTING", "ROUTED", "ROUTE_HELD", "IN_PROCESS",
        "AWAITING_INSPECTION", "AWAITING_LOT_TEST", "REJECTED", "STRIPPING",
        "COMPLETE", "SHIPPED", "SCRAPPED", "CANCELLED",
    )


def assert_load_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["bath_id"], str)
    assert data["duration_minutes"] >= 1
    assert data["current_density_a_dm2"] > 0
    assert isinstance(data["estimated_amp_hours"], (int, float))
    assert data["status"] in ("RUNNING", "COMPLETED", "ABORTED")
    assert is_iso8601_timestamp(data.get("started_at", ""))


def assert_inspection_report(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["load_run_id"], str)
    assert isinstance(data["thickness_readings_um"], list)
    assert len(data["thickness_readings_um"]) >= 3
    assert data["defect_type"] in (
        "NONE", "BURN", "STAIN", "PITTING", "ADHESION", "UNDERTHICKNESS",
    )
    assert data["disposition"] in ("PASS", "REWORKABLE_REJECT", "SCRAP_REJECT")


def assert_salt_spray_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert data["sample_count"] >= 1
    assert data["hours_required"] >= 1
    assert data["allowed_failures"] in (0, 1, 2)
    assert data["result"] in ("PENDING", "PASSED", "FAILED")


def assert_discharge_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["outfall_code"], str)
    assert isinstance(data["limits"], list) and len(data["limits"]) >= 1
    assert data["status"] in ("ACTIVE", "EXCEEDED")
    assert isinstance(data["exceedance_active"], bool)
    assert isinstance(data["cumulative_mass_g"], dict)


def assert_waste_sample(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["permit_id"], str)
    assert data["flow_liters"] > 0
    assert isinstance(data["readings"], list) and len(data["readings"]) >= 1
    assert isinstance(data["masses_g"], dict)
    assert isinstance(data["is_exceedance"], bool)


def assert_waste_manifest(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["generator_epa_id"], str)
    assert isinstance(data["created_by_user_id"], str)
    assert isinstance(data["total_mass_kg"], (int, float))
    assert data["total_mass_kg"] >= 0
    assert data["status"] in ("DRAFT", "FINALIZED", "SHIPPED", "RECEIVED")


def assert_manifest_line_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["manifest_id"], str)
    assert isinstance(data["waste_code"], str)
    assert data["source_type"] in ("BATH_DUMP", "SLUDGE_PRESS", "RINSE_CONCENTRATE")
    assert data["volume_liters"] > 0
    assert isinstance(data["mass_kg"], (int, float))
    assert data["mass_kg"] > 0


def assert_bath_amp_hour_invariants(bath: dict, expected_reserved=None, expected_used=None):
    """Amp-hour account invariants (PRD §3.3)."""
    assert bath["amp_hour_used"] >= 0, "amp_hour_used must be non-negative"
    assert bath["amp_hour_reserved"] >= 0, "amp_hour_reserved must be non-negative"
    if expected_reserved is not None:
        assert bath["amp_hour_reserved"] == expected_reserved, (
            f"amp_hour_reserved: expected {expected_reserved}, got {bath['amp_hour_reserved']}"
        )
    if expected_used is not None:
        assert bath["amp_hour_used"] == expected_used, (
            f"amp_hour_used: expected {expected_used}, got {bath['amp_hour_used']}"
        )
