"""Payload factories — one per write surface, request-input fields only."""

from .constants import (
    A1_PROGRAM_DEFAULTS,
    A2L_PROGRAM_DEFAULTS,
    DEFAULT_CLOCK_UTC,
    HIGH_A2L_PLATFORM_DEFAULTS,
    NORTHEAST_STANDARD_DEFAULTS,
    SOUTHEAST_STANDARD_DEFAULTS,
    STANDARD_A1_PLATFORM_DEFAULTS,
)


def set_clock_payload(current_utc: str = DEFAULT_CLOCK_UTC, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# --- Refrigerant programs ---------------------------------------------------


def a2l_program_payload(**overrides) -> dict:
    payload = dict(A2L_PROGRAM_DEFAULTS)
    payload.update(overrides)
    return payload


def a1_program_payload(**overrides) -> dict:
    payload = dict(A1_PROGRAM_DEFAULTS)
    payload.update(overrides)
    return payload


def create_refrigerant_program_payload(**overrides) -> dict:
    return a2l_program_payload(**overrides)


# --- Regional standards -----------------------------------------------------


def southeast_standard_payload(**overrides) -> dict:
    payload = dict(SOUTHEAST_STANDARD_DEFAULTS)
    payload.update(overrides)
    return payload


def northeast_standard_payload(**overrides) -> dict:
    payload = dict(NORTHEAST_STANDARD_DEFAULTS)
    payload.update(overrides)
    return payload


def create_regional_standard_payload(**overrides) -> dict:
    return southeast_standard_payload(**overrides)


# --- Product platforms ------------------------------------------------------


def high_a2l_platform_payload(refrigerant_program_id: str, **overrides) -> dict:
    payload = dict(HIGH_A2L_PLATFORM_DEFAULTS)
    payload["refrigerant_program_id"] = refrigerant_program_id
    payload.update(overrides)
    return payload


def standard_a1_platform_payload(refrigerant_program_id: str, **overrides) -> dict:
    payload = dict(STANDARD_A1_PLATFORM_DEFAULTS)
    payload["refrigerant_program_id"] = refrigerant_program_id
    payload.update(overrides)
    return payload


def create_product_platform_payload(refrigerant_program_id: str, **overrides) -> dict:
    return high_a2l_platform_payload(refrigerant_program_id, **overrides)


def return_to_draft_payload(
    revision_notes: str = "Coil circuit revision required for the A2L charge limit",
    **overrides,
) -> dict:
    payload = {"revision_notes": revision_notes}
    payload.update(overrides)
    return payload


def retire_platform_payload(reason: str = "Model line discontinued", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# --- Certification records --------------------------------------------------


def create_certification_record_payload(
    platform_id: str,
    expected_platform_version: int,
    region_code: str = "SOUTHEAST",
    rated_seer2_submitted: float = 15.80,
    **overrides,
) -> dict:
    payload = {
        "platform_id": platform_id,
        "region_code": region_code,
        "rated_seer2_submitted": rated_seer2_submitted,
        "expected_platform_version": expected_platform_version,
    }
    payload.update(overrides)
    return payload


def decide_certification_payload(decision: str = "CERTIFIED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def reject_certification_payload(
    rejection_reason: str = "SEER2 test report incomplete", **overrides
) -> dict:
    payload = {"decision": "REJECTED", "rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# --- Component supplies -----------------------------------------------------


def compressor_supply_payload(
    part_number: str = "CMP-5T-A2L",
    supplier_lot_code: str = "LOT-CMP-51",
    supply_month: str = "2026-11",
    total_allocatable_units: int = 100,
    **overrides,
) -> dict:
    payload = {
        "component_type": "COMPRESSOR",
        "part_number": part_number,
        "supplier_lot_code": supplier_lot_code,
        "supply_month": supply_month,
        "total_allocatable_units": total_allocatable_units,
    }
    payload.update(overrides)
    return payload


def control_board_supply_payload(
    part_number: str = "CTL-9X",
    supplier_lot_code: str = "LOT-CTL-77",
    supply_month: str = "2026-11",
    total_allocatable_units: int = 100,
    **overrides,
) -> dict:
    payload = {
        "component_type": "CONTROL_BOARD",
        "part_number": part_number,
        "supplier_lot_code": supplier_lot_code,
        "supply_month": supply_month,
        "total_allocatable_units": total_allocatable_units,
    }
    payload.update(overrides)
    return payload


def create_component_supply_payload(**overrides) -> dict:
    return compressor_supply_payload(**overrides)


# --- Distributor orders -----------------------------------------------------


def create_distributor_order_payload(
    platform_id: str,
    distributor_code: str = "DIST-SE-1",
    region_code: str = "SOUTHEAST",
    requested_units: int = 30,
    priority_score: int = 70,
    requested_delivery_month: str = "2026-11",
    **overrides,
) -> dict:
    payload = {
        "distributor_code": distributor_code,
        "platform_id": platform_id,
        "region_code": region_code,
        "requested_units": requested_units,
        "priority_score": priority_score,
        "requested_delivery_month": requested_delivery_month,
    }
    payload.update(overrides)
    return payload


def allocate_payload(expected_component_supply_version: int, **overrides) -> dict:
    payload = {"expected_component_supply_version": expected_component_supply_version}
    payload.update(overrides)
    return payload


def ship_payload(shipped_units: int, **overrides) -> dict:
    payload = {"shipped_units": shipped_units}
    payload.update(overrides)
    return payload


def cancel_order_payload(
    reason: str = "Distributor withdrew the pre-season order", **overrides
) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# --- Warehouses and reservations -------------------------------------------


def create_warehouse_payload(
    name: str = "WH-1", pallet_capacity: int = 50, **overrides
) -> dict:
    payload = {"name": name, "pallet_capacity": pallet_capacity}
    payload.update(overrides)
    return payload


def create_warehouse_reservation_payload(
    warehouse_id: str,
    build_order_id: str,
    start_date: str = "2026-11-02",
    end_date: str = "2026-11-20",
    pallet_units: int = 10,
    **overrides,
) -> dict:
    payload = {
        "warehouse_id": warehouse_id,
        "build_order_id": build_order_id,
        "start_date": start_date,
        "end_date": end_date,
        "pallet_units": pallet_units,
    }
    payload.update(overrides)
    return payload


def release_reservation_payload(
    release_reason: str = "Pre-season plan rebalanced", **overrides
) -> dict:
    payload = {"release_reason": release_reason}
    payload.update(overrides)
    return payload


# --- Test cells -------------------------------------------------------------


def create_test_cell_payload(cell_code: str = "CELL-1", **overrides) -> dict:
    payload = {"cell_code": cell_code}
    payload.update(overrides)
    return payload


# --- Build orders -----------------------------------------------------------


def create_build_order_payload(
    platform_id: str,
    quantity_units: int = 20,
    scheduled_start_utc: str = "2026-08-05T08:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "platform_id": platform_id,
        "quantity_units": quantity_units,
        "scheduled_start_utc": scheduled_start_utc,
    }
    payload.update(overrides)
    return payload


def charge_payload(charge_grams: int = 1750, **overrides) -> dict:
    payload = {"charge_grams": charge_grams}
    payload.update(overrides)
    return payload


def cancel_build_order_payload(reason: str = "Pre-season plan trimmed", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# --- Leak tests -------------------------------------------------------------


def helium_leak_test_payload(
    build_order_id: str, measured_leak_rate_g_per_year: float = 1.20, **overrides
) -> dict:
    payload = {
        "build_order_id": build_order_id,
        "method": "HELIUM_MASS_SPEC",
        "measured_leak_rate_g_per_year": measured_leak_rate_g_per_year,
    }
    payload.update(overrides)
    return payload


def pressure_decay_leak_test_payload(
    build_order_id: str, decay_kpa: float = 1.90, hold_minutes: int = 30, **overrides
) -> dict:
    payload = {
        "build_order_id": build_order_id,
        "method": "PRESSURE_DECAY",
        "decay_kpa": decay_kpa,
        "hold_minutes": hold_minutes,
    }
    payload.update(overrides)
    return payload


def create_leak_test_payload(build_order_id: str, **overrides) -> dict:
    return helium_leak_test_payload(build_order_id, **overrides)


# --- Run tests --------------------------------------------------------------


def create_run_test_payload(
    build_order_id: str,
    test_cell_id: str,
    window_start_utc: str = "2026-08-05T08:00:00Z",
    window_end_utc: str = "2026-08-05T09:00:00Z",
    measured_capacity_btuh: int = 36000,
    measured_power_w: int = 2850,
    measured_ambient_c: float = 33.0,
    **overrides,
) -> dict:
    payload = {
        "build_order_id": build_order_id,
        "test_cell_id": test_cell_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "measured_capacity_btuh": measured_capacity_btuh,
        "measured_power_w": measured_power_w,
        "measured_ambient_c": measured_ambient_c,
    }
    payload.update(overrides)
    return payload


# --- Warranty claims --------------------------------------------------------


def create_warranty_claim_payload(
    platform_id: str,
    failure_code: str = "COMPRESSOR_FAILURE",
    claim_cost_cents: int = 41500,
    component_type: str = "COMPRESSOR",
    supplier_lot_code: str = "LOT-CMP-51",
    **overrides,
) -> dict:
    payload = {
        "platform_id": platform_id,
        "failure_code": failure_code,
        "claim_cost_cents": claim_cost_cents,
    }
    if component_type is not None:
        payload["component_type"] = component_type
    if supplier_lot_code is not None:
        payload["supplier_lot_code"] = supplier_lot_code
    payload.update(overrides)
    return payload


# --- Supplier corrective actions -------------------------------------------


def close_corrective_action_payload(
    resolution: str = "EFFECTIVE", effectiveness_note: str = None, **overrides
) -> dict:
    payload = {"resolution": resolution}
    if effectiveness_note is not None:
        payload["effectiveness_note"] = effectiveness_note
    payload.update(overrides)
    return payload
