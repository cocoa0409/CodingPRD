"""Entity assertions and domain invariant checkers."""

from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllocationStatus,
    AssemblyLineStatus,
    BuildOrderStatus,
    CertificationFamilyStatus,
    CertificationPosture,
    ComponentCategory,
    ComponentLotStatus,
    Criticality,
    DeteriorationMethod,
    DurabilityTestRunStatus,
    EngineUnitBuildState,
    EngineUnitConformanceState,
    IncomingInspectionLevel,
    MachiningRunStatus,
    PartsFulfillmentRequestStatus,
    ProductModelStatus,
    ProductionLineAuditStatus,
    SafetyCertificationResult,
    ServicePartStatus,
    SupplierApprovalStatus,
)


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict, entity_label: str) -> None:
    """Every resource but the immutable safety certification carries these."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(
        data.get("version"), int
    ), f"{entity_label}.version must be an integer"
    assert data["version"] >= 1, f"{entity_label}.version starts at 1"


def assert_id_only_fields(data: dict, entity_label: str) -> None:
    """For the immutable bench-test record: only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be an ISO 8601 UTC timestamp"


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def assert_envelope_meta(body: dict) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith(
        "req_"
    ), "meta.api_request_id must start with req_"
    assert is_iso8601_timestamp(
        meta["api_request_timestamp"]
    ), "meta.api_request_timestamp must be an ISO 8601 UTC timestamp"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_certification_family(data: dict) -> None:
    assert_common_fields(data, "CertificationFamily")
    assert isinstance(data["family_code"], str) and data["family_code"]
    assert 2026 <= data["model_year"] <= 2035
    assert data["emission_standard"] in ("EPA_PHASE3", "CARB_2024")
    assert data["displacement_min_cc"] <= data["displacement_max_cc"]
    assert data["durability_hours"] in (125, 250, 500, 1000)
    assert data["family_emission_limit_g_per_kwh"] > 0
    assert data["declared_baseline_emission_g_per_kwh"] > 0
    assert data["status"] in _values(CertificationFamilyStatus)
    assert isinstance(data["cumulative_audit_failures"], int)
    assert data["cumulative_audit_failures"] >= 0


def assert_engine_platform(data: dict) -> None:
    assert_common_fields(data, "EnginePlatform")
    assert isinstance(data["platform_code"], str) and data["platform_code"]
    assert 50 <= data["displacement_cc"] <= 1000
    assert data["torque_spec_nm"] > 0
    assert 0.01 <= data["torque_tolerance_pct"] <= 0.20
    assert 1 <= data["required_fastener_count"] <= 12
    assert 500 <= data["hot_test_min_rpm"] <= 8000
    assert data["hot_test_max_rpm"] > data["hot_test_min_rpm"]
    assert data["certification_posture"] in _values(CertificationPosture)


def assert_durability_test_run(data: dict) -> None:
    assert_common_fields(data, "DurabilityTestRun")
    assert data["status"] in _values(DurabilityTestRunStatus)
    assert data["df_method"] in _values(DeteriorationMethod)
    assert data["scheduled_end_at"] > data["scheduled_start_at"]
    assert 1 <= data["target_hours"] <= 2000
    assert data["initial_emission_g_per_kwh"] > 0
    assert isinstance(data["extrapolated"], bool)


def assert_product_model(data: dict) -> None:
    assert_common_fields(data, "ProductModel")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["product_line"] in (
        "WALK_MOWER",
        "RIDING_MOWER",
        "SNOW_THROWER",
        "GENERATOR",
    )
    assert data["channel"] in ("DEALER", "MASS_RETAIL", "DUAL")
    assert data["blade_brake_type"] in ("BLADE_BRAKE_CLUTCH", "ENGINE_KILL", "NONE")
    assert data["operator_presence_type"] in (
        "BAIL",
        "SEAT_SWITCH",
        "TWO_HAND",
        "CO_SHUTOFF",
    )
    assert 12 <= data["warranty_months"] <= 120
    assert data["standard_cost_cents"] >= 1
    assert data["msrp_cents"] >= data["standard_cost_cents"]
    assert 0.00 <= data["dealer_share_pct"] <= 1.00
    assert data["dealer_cap_units"] >= 0
    assert data["mass_retail_cap_units"] >= 0
    assert data["status"] in _values(ProductModelStatus)


def assert_safety_certification(data: dict) -> None:
    """The bench-test record is immutable: no updated_at, no version."""
    assert_id_only_fields(data, "SafetyCertification")
    assert data["standard_code"] in ("ANSI_B71_1", "ANSI_B71_3", "UL_2201")
    assert 1 <= data["opc_stop_time_ms"] <= 10000
    assert data["expires_on"] > data["tested_on"]
    assert data["result"] in _values(SafetyCertificationResult)
    assert isinstance(data["tested_by_user_id"], str) and data["tested_by_user_id"]
    assert (
        "updated_at" not in data
    ), "SafetyCertification must not carry updated_at"
    assert "version" not in data, "SafetyCertification must not carry version"


def assert_supplier(data: dict) -> None:
    assert_common_fields(data, "Supplier")
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["component_category"] in _values(ComponentCategory)
    assert data["criticality"] in _values(Criticality)
    assert data["approval_status"] in _values(SupplierApprovalStatus)
    assert data["incoming_inspection_level"] in _values(IncomingInspectionLevel)
    assert isinstance(data["rolling_defect_ppm"], int)
    assert data["inspected_lot_count"] >= 0
    assert data["consecutive_accepted_lots"] >= 0


def assert_component_lot(data: dict) -> None:
    assert_common_fields(data, "ComponentLot")
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert 1 <= data["lot_quantity"] <= 100000
    assert data["component_category"] in _values(ComponentCategory)
    assert data["status"] in _values(ComponentLotStatus)
    assert data["inspection_level_at_receipt"] in _values(IncomingInspectionLevel)
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 0
    assert isinstance(data["acceptance_number"], int)
    assert isinstance(data["deviation_flag"], bool)
    assert_lot_piece_conservation(data)


def assert_machining_run(data: dict) -> None:
    assert_common_fields(data, "MachiningRun")
    assert data["component_type"] in ("CRANKSHAFT", "CYLINDER_BORE", "CAMSHAFT")
    assert data["criticality"] in _values(Criticality)
    assert data["usl_mm"] > data["lsl_mm"]
    assert data["status"] in _values(MachiningRunStatus)
    assert isinstance(data["sample_count"], int) and data["sample_count"] >= 0


def assert_assembly_line(data: dict) -> None:
    assert_common_fields(data, "AssemblyLine")
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["supported_product_lines"], list)
    assert data["supported_product_lines"], "supported_product_lines must be non-empty"
    assert 1 <= data["weekly_capacity_units"] <= 100000
    assert 0 <= data["changeover_gap_weeks"] <= 4
    assert data["status"] in _values(AssemblyLineStatus)


def assert_build_order(data: dict) -> None:
    assert_common_fields(data, "BuildOrder")
    assert data["season"] in ("PRE_SEASON", "IN_SEASON")
    assert 1 <= data["week_span"] <= 8
    assert 1 <= data["planned_quantity"] <= 100000
    assert data["status"] in _values(BuildOrderStatus)
    assert data["allocation_status"] in _values(AllocationStatus)
    assert data["staged_quantity"] >= 0
    assert data["built_quantity"] >= 0
    assert_build_order_unit_conservation(data)


def assert_engine_unit(data: dict) -> None:
    assert_common_fields(data, "EngineUnit")
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["build_state"] in _values(EngineUnitBuildState)
    assert data["conformance_state"] in _values(EngineUnitConformanceState)
    assert isinstance(data["deviation_sourced"], bool)
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0


def assert_production_line_audit(data: dict) -> None:
    assert_common_fields(data, "ProductionLineAudit")
    assert data["status"] in _values(ProductionLineAuditStatus)
    assert isinstance(data["required_sample_size"], int)
    assert data["required_sample_size"] >= 2


def assert_service_part(data: dict) -> None:
    assert_common_fields(data, "ServicePart")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["category"] in (
        "CARBURETOR_KIT",
        "IGNITION_MODULE",
        "BLADE_ASSEMBLY",
        "FILTER_KIT",
    )
    assert data["on_hand_qty"] >= 0
    assert data["committed_availability_years"] >= 7
    assert 2020 <= data["last_production_year"] <= 2060
    assert (
        data["commitment_expires_year"]
        == data["last_production_year"] + data["committed_availability_years"]
    ), "commitment_expires_year is last_production_year plus committed_availability_years"
    assert 1 <= data["dealer_lead_time_days"] <= 30
    assert 1 <= data["mass_retail_lead_time_days"] <= 60
    assert data["status"] in _values(ServicePartStatus)
    assert data["filled_request_count"] >= 0
    assert data["substituted_request_count"] >= 0
    assert data["backordered_request_count"] >= 0


def assert_parts_fulfillment_request(data: dict) -> None:
    assert_common_fields(data, "PartsFulfillmentRequest")
    assert data["requested_quantity"] >= 1
    assert data["channel"] in ("DEALER", "MASS_RETAIL")
    assert data["status"] in _values(PartsFulfillmentRequestStatus)
    assert isinstance(data["requester_user_id"], str) and data["requester_user_id"]


# ---------------------------------------------------------------------------
# Conserved quantities (PRD §2.11)
# ---------------------------------------------------------------------------


def assert_lot_piece_conservation(lot: dict) -> None:
    """accepted_qty always equals consumed_qty plus remaining_qty."""
    assert lot["accepted_qty"] == lot["consumed_qty"] + lot["remaining_qty"], (
        "Lot piece conservation broken: accepted_qty "
        f"{lot['accepted_qty']} != consumed_qty {lot['consumed_qty']} + "
        f"remaining_qty {lot['remaining_qty']}"
    )


def assert_build_order_unit_conservation(order: dict) -> None:
    """built_quantity always equals the three channel buckets summed."""
    total = (
        order["allocated_dealer_units"]
        + order["allocated_mass_retail_units"]
        + order["unallocated_units"]
    )
    assert order["built_quantity"] == total, (
        "Build order unit conservation broken: built_quantity "
        f"{order['built_quantity']} != dealer {order['allocated_dealer_units']} + "
        f"mass retail {order['allocated_mass_retail_units']} + unallocated "
        f"{order['unallocated_units']}"
    )


# ---------------------------------------------------------------------------
# Numeric scale helpers (PRD §2.6)
# ---------------------------------------------------------------------------


def assert_decimal_places(value: float, places: int, label: str) -> None:
    assert value is not None, f"{label} must be present"
    quantised = round(float(value), places)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{label} must carry at most {places} decimal places, got {value}"
    )


def assert_whole_cents(value, label: str) -> None:
    assert isinstance(value, int), f"{label} must be held in whole cents"


def assert_version_advanced_by(before: int, after: int, steps: int, label: str) -> None:
    assert after == before + steps, (
        f"{label} version should advance by {steps}: was {before}, now {after}"
    )


def assert_optional_absent(value: Optional[object], label: str) -> None:
    assert value is None, f"{label} must be empty, got {value!r}"
