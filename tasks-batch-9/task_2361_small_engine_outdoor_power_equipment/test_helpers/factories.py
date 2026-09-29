"""Payload factories — one per created resource, input fields only."""

import itertools

from .constants import (
    CANONICAL_CLOCK_UTC,
    FAMILY_DECLARED_BASELINE,
    FAMILY_DURABILITY_HOURS,
    FAMILY_EMISSION_LIMIT,
    HOT_TEST_MAX_RPM,
    HOT_TEST_MIN_RPM,
    HOT_TEST_NOMINAL_RPM,
    HOT_TEST_PASSING_EMISSION,
    IN_BAND_TORQUE_READINGS,
    LOT_QUANTITY,
    MACHINING_LSL_MM,
    MACHINING_USL_MM,
    MODEL_DEALER_SHARE_PCT,
    MODEL_MSRP_CENTS,
    MODEL_STANDARD_COST_CENTS,
    PLATFORM_REQUIRED_FASTENER_COUNT,
    PLATFORM_TORQUE_SPEC_NM,
    PLATFORM_TORQUE_TOLERANCE_PCT,
    CAPABLE_MEASUREMENTS,
    DURABILITY_FINAL_EMISSION,
    DURABILITY_INITIAL_EMISSION,
)

_sequence = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix guaranteeing code uniqueness inside a single test."""
    return f"{next(_sequence):04d}"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock_payload(to_iso8601: str = CANONICAL_CLOCK_UTC, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Certification families and platforms
# ---------------------------------------------------------------------------


def create_certification_family_payload(**overrides) -> dict:
    payload = {
        "family_code": "2027-EPA-208SS",
        "model_year": 2027,
        "emission_standard": "EPA_PHASE3",
        "displacement_min_cc": 190,
        "displacement_max_cc": 224,
        "durability_hours": FAMILY_DURABILITY_HOURS,
        "family_emission_limit_g_per_kwh": FAMILY_EMISSION_LIMIT,
        "declared_baseline_emission_g_per_kwh": FAMILY_DECLARED_BASELINE,
    }
    payload.update(overrides)
    return payload


def create_engine_platform_payload(certification_family_id: str, **overrides) -> dict:
    payload = {
        "certification_family_id": certification_family_id,
        "platform_code": "208SS",
        "displacement_cc": 208,
        "torque_spec_nm": PLATFORM_TORQUE_SPEC_NM,
        "torque_tolerance_pct": PLATFORM_TORQUE_TOLERANCE_PCT,
        "required_fastener_count": PLATFORM_REQUIRED_FASTENER_COUNT,
        "hot_test_min_rpm": HOT_TEST_MIN_RPM,
        "hot_test_max_rpm": HOT_TEST_MAX_RPM,
    }
    payload.update(overrides)
    return payload


def create_durability_test_payload(
    certification_family_id: str,
    engine_platform_id: str,
    expected_certification_family_version: int,
    **overrides,
) -> dict:
    payload = {
        "certification_family_id": certification_family_id,
        "engine_platform_id": engine_platform_id,
        "scheduled_start_at": "2026-08-03T09:00:00Z",
        "scheduled_end_at": "2026-08-24T09:00:00Z",
        "target_hours": FAMILY_DURABILITY_HOURS,
        "initial_emission_g_per_kwh": DURABILITY_INITIAL_EMISSION,
        "expected_certification_family_version": expected_certification_family_version,
    }
    payload.update(overrides)
    return payload


def complete_durability_test_payload(**overrides) -> dict:
    payload = {
        "accumulated_hours": FAMILY_DURABILITY_HOURS,
        "final_emission_g_per_kwh": DURABILITY_FINAL_EMISSION,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Product models and safety certifications
# ---------------------------------------------------------------------------


def create_product_model_payload(engine_platform_id: str, **overrides) -> dict:
    payload = {
        "engine_platform_id": engine_platform_id,
        "model_code": "WM-21-BBC",
        "product_line": "WALK_MOWER",
        "channel": "DUAL",
        "blade_brake_type": "BLADE_BRAKE_CLUTCH",
        "operator_presence_type": "BAIL",
        "warranty_months": 36,
        "standard_cost_cents": MODEL_STANDARD_COST_CENTS,
        "msrp_cents": MODEL_MSRP_CENTS,
        "dealer_share_pct": MODEL_DEALER_SHARE_PCT,
        "dealer_cap_units": 500,
        "mass_retail_cap_units": 500,
    }
    payload.update(overrides)
    return payload


def create_safety_certification_payload(product_model_id: str, **overrides) -> dict:
    payload = {
        "product_model_id": product_model_id,
        "standard_code": "ANSI_B71_1",
        "blade_stop_time_ms": 2600,
        "opc_stop_time_ms": 900,
        "tested_on": "2026-07-15",
        "expires_on": "2027-07-15",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Suppliers, lots and machining runs
# ---------------------------------------------------------------------------


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "supplier_code": "SUP-CARB",
        "name": "Kirin Carburetor Works",
        "component_category": "CARBURETOR",
    }
    payload.update(overrides)
    return payload


def create_component_lot_payload(supplier_id: str, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "lot_code": "CB-001",
        "lot_quantity": LOT_QUANTITY,
    }
    payload.update(overrides)
    return payload


def inspect_component_lot_payload(defects_found: int = 0, **overrides) -> dict:
    payload = {"defects_found": defects_found}
    payload.update(overrides)
    return payload


def create_machining_run_payload(
    engine_platform_id: str, casting_lot_id: str, **overrides
) -> dict:
    payload = {
        "engine_platform_id": engine_platform_id,
        "casting_lot_id": casting_lot_id,
        "component_type": "CYLINDER_BORE",
        "lsl_mm": MACHINING_LSL_MM,
        "usl_mm": MACHINING_USL_MM,
    }
    payload.update(overrides)
    return payload


def close_machining_run_payload(measurements=None, **overrides) -> dict:
    payload = {
        "measurements": list(measurements)
        if measurements is not None
        else list(CAPABLE_MEASUREMENTS)
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Assembly lines and build orders
# ---------------------------------------------------------------------------


def create_assembly_line_payload(**overrides) -> dict:
    payload = {
        "line_code": "L1",
        "supported_product_lines": ["WALK_MOWER", "SNOW_THROWER"],
        "weekly_capacity_units": 500,
        "changeover_gap_weeks": 1,
        "status": "RUNNING",
    }
    payload.update(overrides)
    return payload


def create_build_order_payload(
    product_model_id: str, assembly_line_id: str, **overrides
) -> dict:
    payload = {
        "product_model_id": product_model_id,
        "assembly_line_id": assembly_line_id,
        "season": "PRE_SEASON",
        "production_week": "2026-09-14",
        "week_span": 2,
        "planned_quantity": 6,
    }
    payload.update(overrides)
    return payload


def run_allocations_payload(expected_build_order_version: int, **overrides) -> dict:
    payload = {"expected_build_order_version": expected_build_order_version}
    payload.update(overrides)
    return payload


def create_line_audit_payload(audit_week: str = "2026-09-14", **overrides) -> dict:
    payload = {"audit_week": audit_week}
    payload.update(overrides)
    return payload


def record_line_audit_payload(
    units_tested: int = 2,
    units_failed: int = 0,
    max_measured_emission_g_per_kwh: float = HOT_TEST_PASSING_EMISSION,
    **overrides,
) -> dict:
    payload = {
        "units_tested": units_tested,
        "units_failed": units_failed,
        "max_measured_emission_g_per_kwh": max_measured_emission_g_per_kwh,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Engine units
# ---------------------------------------------------------------------------


def create_engine_unit_payload(
    build_order_id: str,
    machining_run_id: str,
    carburetor_lot_id: str,
    ignition_lot_id: str,
    serial_number: str = "SN-0001",
    **overrides,
) -> dict:
    payload = {
        "build_order_id": build_order_id,
        "machining_run_id": machining_run_id,
        "carburetor_lot_id": carburetor_lot_id,
        "ignition_lot_id": ignition_lot_id,
        "serial_number": serial_number,
    }
    payload.update(overrides)
    return payload


def torque_record_payload(torque_readings=None, **overrides) -> dict:
    payload = {
        "torque_readings": [dict(r) for r in torque_readings]
        if torque_readings is not None
        else [dict(r) for r in IN_BAND_TORQUE_READINGS]
    }
    payload.update(overrides)
    return payload


def torque_readings_at(*values) -> list:
    """Build a reading array from bare torque values, one station per value."""
    return [
        {"station": index, "torque_nm": value} for index, value in enumerate(values, 1)
    ]


def hot_test_payload(
    measured_rpm: int = HOT_TEST_NOMINAL_RPM,
    measured_emission_g_per_kwh: float = HOT_TEST_PASSING_EMISSION,
    **overrides,
) -> dict:
    payload = {
        "measured_rpm": measured_rpm,
        "measured_emission_g_per_kwh": measured_emission_g_per_kwh,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Service parts and fulfillment requests
# ---------------------------------------------------------------------------


def create_service_part_payload(engine_platform_id: str, **overrides) -> dict:
    payload = {
        "engine_platform_id": engine_platform_id,
        "part_number": "PN-CARB-KIT-1",
        "category": "CARBURETOR_KIT",
        "on_hand_qty": 5,
        "committed_availability_years": 10,
        "last_production_year": 2027,
        "dealer_lead_time_days": 2,
        "mass_retail_lead_time_days": 5,
    }
    payload.update(overrides)
    return payload


def supersede_service_part_payload(successor_part_id: str, **overrides) -> dict:
    payload = {"successor_part_id": successor_part_id}
    payload.update(overrides)
    return payload


def create_parts_request_payload(service_part_id: str, **overrides) -> dict:
    payload = {
        "service_part_id": service_part_id,
        "requested_quantity": 1,
        "channel": "DEALER",
    }
    payload.update(overrides)
    return payload
