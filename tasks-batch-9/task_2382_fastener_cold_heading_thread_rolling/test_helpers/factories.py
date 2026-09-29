"""Payload factories — one per resource, input fields only.

Every default here is a legal value under the PRD's declared constraints, so a
factory call with no overrides always produces an acceptable payload. Tests
override exactly the fields the claim under test cares about.
"""

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Shared reference values used across the suite
# ---------------------------------------------------------------------------
REFERENCE = {
    # Part spec (CLASS_10_9 / ZINC_CLEAR => he_bake_required true, 240 minutes)
    "PART_NUMBER": "HX-M8-109",
    "THREAD_DESIGNATION": "M8x1.25",
    "BLANK_MASS_G": 20.0,
    # Steel heat / wire lot
    "HEAT_NUMBER": "H-77410",
    "MILL_CODE": "MC-A",
    "MILL_CERT_SERIAL": "MC-2026-000481",
    "LAB_REPORT_REFERENCE": "LAB-0001",
    # Tool / furnace / press
    "TOOL_CODE": "DIE-4S-001",
    "PRESS_CODE": "PRESS-3",
    "FURNACE_CODE": "FCE-1",
    # Lot
    "LOT_CODE": "L-2601",
    "PRESS_WINDOW_START": "2026-09-01T06:00:00Z",
    "PRESS_WINDOW_END": "2026-09-01T10:00:00Z",
    # Certificate / pack
    "CERT_SERIAL": "COC-2026-0001",
    "LABEL_SERIAL": "PK-2026-0001",
}


def create_part_spec_payload(**overrides: Any) -> Dict[str, Any]:
    """A plated CLASS_10_9 part rolled before heat treatment, packed by count."""
    payload: Dict[str, Any] = {
        "part_number": REFERENCE["PART_NUMBER"],
        "thread_designation": REFERENCE["THREAD_DESIGNATION"],
        "strength_class": "CLASS_10_9",
        "qualification_program": "AUTOMOTIVE_PPAP",
        "allowed_steel_grades": ["SAE_10B21"],
        "blank_mass_g": REFERENCE["BLANK_MASS_G"],
        "station_count_required": 4,
        "thread_timing": "BEFORE_HEAT_TREAT",
        "required_secondary_ops": ["THREAD_ROLL"],
        "min_core_hardness_hv": 304,
        "max_core_hardness_hv": 361,
        "max_decarb_depth_mm": 0.150,
        "plating_spec": "ZINC_CLEAR",
        "packaging_mode": "BY_COUNT",
        "nominal_pack_count": 100,
        "pieces_per_kg": 50.0,
        "proof_load_kn": 34.7,
    }
    payload.update(overrides)
    return payload


def create_unplated_part_spec_payload(**overrides: Any) -> Dict[str, Any]:
    """An unplated CLASS_10_9 part: plating_spec NONE, so he_bake_required is false."""
    defaults = create_part_spec_payload(
        part_number="NP-M8-088",
        plating_spec="NONE",
    )
    defaults.update(overrides)
    return defaults


def create_steel_heat_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "heat_number": REFERENCE["HEAT_NUMBER"],
        "mill_code": REFERENCE["MILL_CODE"],
        "grade": "SAE_10B21",
        "carbon_pct": 0.21,
        "boron_ppm": 25,
        "gross_mass_kg": 500.0,
        "mill_cert_serial": REFERENCE["MILL_CERT_SERIAL"],
    }
    payload.update(overrides)
    return payload


def verify_mill_cert_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": "VERIFIED",
        "mill_cert_serial": REFERENCE["MILL_CERT_SERIAL"],
        "lab_report_reference": REFERENCE["LAB_REPORT_REFERENCE"],
    }
    payload.update(overrides)
    return payload


def create_wire_lot_payload(steel_heat_id: str, **overrides: Any) -> Dict[str, Any]:
    """8.00 -> 6.80 mm gives reduction_pct 27.75, inside the 8.0-35.0 band."""
    payload: Dict[str, Any] = {
        "steel_heat_id": steel_heat_id,
        "draw_pass_count": 3,
        "inlet_diameter_mm": 8.00,
        "outlet_diameter_mm": 6.80,
        "lubricant_coating": "PHOSPHATE",
        "coating_weight_gsm": 4.5,
        "gross_mass_kg": 500.0,
    }
    payload.update(overrides)
    return payload


def create_heading_tool_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tool_code": REFERENCE["TOOL_CODE"],
        "station_count": 4,
        "rated_life_pieces": 120000,
    }
    payload.update(overrides)
    return payload


def create_furnace_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "furnace_code": REFERENCE["FURNACE_CODE"],
        "max_charge_mass_kg": 400.0,
    }
    payload.update(overrides)
    return payload


def create_production_lot_payload(
    part_spec_id: str,
    wire_lot_id: str,
    heading_tool_id: str,
    expected_wire_lot_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lot_code": REFERENCE["LOT_CODE"],
        "part_spec_id": part_spec_id,
        "wire_lot_id": wire_lot_id,
        "heading_tool_id": heading_tool_id,
        "press_code": REFERENCE["PRESS_CODE"],
        "press_window_start_at": REFERENCE["PRESS_WINDOW_START"],
        "press_window_end_at": REFERENCE["PRESS_WINDOW_END"],
        "planned_pieces": 5000,
        "expected_wire_lot_version": expected_wire_lot_version,
    }
    payload.update(overrides)
    return payload


def complete_heading_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"headed_count": 4900, "heading_scrap_count": 60}
    payload.update(overrides)
    return payload


def queue_secondary_operation_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "op_type": "THREAD_ROLL",
        "sequence_no": 1,
        "machine_code": "TR-1",
    }
    payload.update(overrides)
    return payload


def create_heat_treat_run_payload(
    production_lot_id: str, furnace_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "production_lot_id": production_lot_id,
        "furnace_id": furnace_id,
        "window_start_at": "2026-09-01T18:00:00Z",
        "window_end_at": "2026-09-01T23:00:00Z",
        "austenitize_temp_c": 870.0,
        "quench_medium": "OIL",
        "temper_temp_c": 420.0,
        "temper_time_min": 60,
        "carbon_potential_pct": 0.42,
    }
    payload.update(overrides)
    return payload


def heat_treat_results_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "core_hardness_hv": 330.0,
        "surface_decarb_depth_mm": 0.020,
    }
    payload.update(overrides)
    return payload


def create_plating_run_payload(production_lot_id: str, **overrides: Any) -> Dict[str, Any]:
    """``plating_spec`` and ``load_mass_kg`` are named by the payload but the server
    derives both, per PRD §3.6."""
    payload: Dict[str, Any] = {
        "production_lot_id": production_lot_id,
        "plating_spec": "ZINC_CLEAR",
        "load_mass_kg": 0.0,
    }
    payload.update(overrides)
    return payload


def start_bake_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"bake_temp_c": 210.0, "bake_duration_min": 240}
    payload.update(overrides)
    return payload


def create_lot_test_payload(production_lot_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"production_lot_id": production_lot_id}
    payload.update(overrides)
    return payload


def lot_test_results_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "proof_load_failures": 0,
        "tensile_failures": 0,
        "min_measured_core_hardness_hv": 330.0,
    }
    payload.update(overrides)
    return payload


def create_certification_document_payload(
    production_lot_id: str,
    lot_test_id: str,
    expected_production_lot_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "production_lot_id": production_lot_id,
        "lot_test_id": lot_test_id,
        "cert_serial": REFERENCE["CERT_SERIAL"],
        "expected_production_lot_version": expected_production_lot_version,
    }
    payload.update(overrides)
    return payload


def create_pack_unit_payload(
    production_lot_id: str, certification_document_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "production_lot_id": production_lot_id,
        "certification_document_id": certification_document_id,
        "label_serial": REFERENCE["LABEL_SERIAL"],
        "actual_count": 100,
        "label_fields_complete": True,
    }
    payload.update(overrides)
    return payload


def reason_payload(reason: str = "OPERATOR_REASON", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload
