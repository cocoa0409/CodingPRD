"""
Payload factories — one per creation endpoint, input fields only.

The defaults describe one coherent shop: an INDUSTRIAL program committed to
500 000 pieces with a 1 000-piece minimum order, a chrome-silicon wire grade at
1900 MPa, and the canonical compression spring D1 (2.5 mm wire, 20 mm outer
diameter, 60 mm free length, 8 active coils, 150 N / 50 N, shot peened). Every
factory takes `**overrides` so a test can move exactly the one field it is
about, and can drop a field entirely by passing it as `None` through
`without()`.
"""

from typing import Any, Dict, List, Optional

from . import constants as C

Json = Dict[str, Any]


def without(payload: Json, *field_names: str) -> Json:
    """Copy of `payload` with the named fields removed (for required-field tests)."""
    return {k: v for k, v in payload.items() if k not in field_names}


# ── CustomerProgram (PRD 3.1) ────────────────────────────────────────────────
def program_payload(**overrides: Any) -> Json:
    payload: Json = {
        "program_code": C.CANONICAL_PROGRAM_CODE,
        "customer_name": "Bramble Industrial Supply",
        "application_class": C.CLASS_INDUSTRIAL,
        "ppap_level": 1,
        "committed_pieces": 500_000,
        "minimum_order_quantity": 1_000,
        "required_salt_spray_hours": 96,
        "biocompatibility_required": False,
        "min_fatigue_margin": 1.2,
        "required_ppk": 1.0,
        "amortization_method": C.FORECAST_BASIS,
    }
    payload.update(overrides)
    return payload


# ── MaterialSpec (PRD 3.1) ───────────────────────────────────────────────────
def material_spec_payload(**overrides: Any) -> Json:
    payload: Json = {
        "spec_code": C.CANONICAL_SPEC_CODE,
        "wire_material": C.WIRE_CHROME_SILICON,
        "tensile_grade_mpa": 1900,
        "shear_modulus_gpa": 79.3,
        "elastic_modulus_gpa": 203.0,
        "density_kg_per_m3": 7850,
        "coating": C.COATING_ZINC_PHOSPHATE,
        "salt_spray_hours": 96,
        "biocompatible": False,
        "cost_per_kg_cents": 850,
    }
    payload.update(overrides)
    return payload


def biocompatible_material_payload(**overrides: Any) -> Json:
    """A passivated stainless grade qualified for implant contact."""
    payload = material_spec_payload(
        spec_code="MS-SS302-1",
        wire_material=C.WIRE_STAINLESS_302,
        tensile_grade_mpa=1650,
        shear_modulus_gpa=69.0,
        elastic_modulus_gpa=193.0,
        density_kg_per_m3=7900,
        coating=C.COATING_PASSIVATED,
        salt_spray_hours=240,
        biocompatible=True,
        cost_per_kg_cents=2200,
    )
    payload.update(overrides)
    return payload


# ── SpringDesign (PRD 3.2) ───────────────────────────────────────────────────
def design_payload(program_id: str, material_spec_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "program_id": program_id,
        "material_spec_id": material_spec_id,
        "part_number": C.CANONICAL_PART_NUMBER,
        "form_type": C.FORM_COMPRESSION,
        "end_type": C.END_CLOSED_GROUND,
        "wire_diameter_mm": 2.5,
        "outer_diameter_mm": 20.0,
        "free_length_mm": 60.0,
        "active_coils": 8,
        "max_working_load_n": 150,
        "min_working_load_n": 50,
        "cycle_seconds_per_piece": 1.8,
        "shot_peening_required": True,
    }
    payload.update(overrides)
    return payload


# ── CriticalCharacteristic (PRD 3.3) ─────────────────────────────────────────
def characteristic_payload(**overrides: Any) -> Json:
    payload: Json = {
        "char_code": C.CHAR_FREE_LENGTH,
        "nominal_value": 60.0,
        "lsl": 59.5,
        "usl": 60.5,
        "is_safety_critical": True,
        "cpk_floor": 1.333,
    }
    payload.update(overrides)
    return payload


def non_safety_characteristic_payload(**overrides: Any) -> Json:
    """A second characteristic whose out-of-control subgroups never hold a run."""
    payload = characteristic_payload(
        char_code=C.CHAR_HOOK_POSITION,
        nominal_value=24.0,
        lsl=23.7,
        usl=24.3,
        is_safety_critical=False,
        cpk_floor=1.0,
    )
    payload.update(overrides)
    return payload


# ── ToolingAsset (PRD 3.4) ───────────────────────────────────────────────────
def tooling_payload(design_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "design_id": design_id,
        "tool_code": C.CANONICAL_TOOL_CODE,
        "original_cost_cents": 4_800_000,
    }
    payload.update(overrides)
    return payload


# ── WireLot (PRD 3.5) ────────────────────────────────────────────────────────
def wire_lot_payload(material_spec_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "material_spec_id": material_spec_id,
        "heat_number": C.CANONICAL_HEAT_NUMBER,
        "received_kg": 800.0,
    }
    payload.update(overrides)
    return payload


def certify_payload(**overrides: Any) -> Json:
    """A tensile test that clears the canonical 1900 MPa grade."""
    payload: Json = {"tensile_test_mpa": 1930}
    payload.update(overrides)
    return payload


# ── CoilingMachine (PRD 3.6) ─────────────────────────────────────────────────
def machine_payload(**overrides: Any) -> Json:
    payload: Json = {
        "machine_code": C.CANONICAL_MACHINE_CODE,
        "max_wire_diameter_mm": 4.0,
        "changeover_buffer_minutes": 45,
    }
    payload.update(overrides)
    return payload


# ── MachineSetup (PRD 3.6) ───────────────────────────────────────────────────
def setup_payload(
    machine_id: str,
    design_id: str,
    tooling_asset_id: str,
    expected_machine_version: int,
    **overrides: Any,
) -> Json:
    payload: Json = {
        "machine_id": machine_id,
        "design_id": design_id,
        "tooling_asset_id": tooling_asset_id,
        "window_start": C.CLOCK_SETUP_DAY_START,
        "window_end": C.CLOCK_SETUP_WINDOW_END,
        "expected_machine_version": expected_machine_version,
    }
    payload.update(overrides)
    return payload


# ── ProductionRun (PRD 3.7) ──────────────────────────────────────────────────
def run_payload(setup_id: str, wire_lot_id: str, design_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "setup_id": setup_id,
        "wire_lot_id": wire_lot_id,
        "design_id": design_id,
        "planned_pieces": 26_000,
    }
    payload.update(overrides)
    return payload


def measurement_payload(
    characteristic_id: str, measurements: Optional[List[float]] = None
) -> Json:
    """A subgroup for the first-article or in-process endpoints."""
    return {
        "characteristic_id": characteristic_id,
        "measurements": list(
            measurements if measurements is not None else C.IN_CONTROL_SUBGROUP
        ),
    }


def completion_payload(produced_pieces: int = 25_500, scrapped_pieces: int = 500) -> Json:
    return {"produced_pieces": produced_pieces, "scrapped_pieces": scrapped_pieces}


# ── StressReliefOven / HeatTreatBatch (PRD 3.9) ──────────────────────────────
def oven_payload(**overrides: Any) -> Json:
    payload: Json = {
        "oven_code": C.CANONICAL_OVEN_CODE,
        "capacity_kg": 600.0,
        "max_temp_c": 450.0,
    }
    payload.update(overrides)
    return payload


def batch_payload(oven_id: str, run_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "oven_id": oven_id,
        "run_id": run_id,
        "window_start": C.CLOCK_BATCH_WINDOW_START,
        "window_end": C.CLOCK_BATCH_WINDOW_END,
        "load_kg": 250.0,
        "target_temp_c": 425.0,
        "peening_requested": True,
    }
    payload.update(overrides)
    return payload


# ── QualificationSubmission (PRD 3.10) ───────────────────────────────────────
def submission_payload(program_id: str, design_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "program_id": program_id,
        "design_id": design_id,
        "ppap_level": 1,
    }
    payload.update(overrides)
    return payload


# ── Quote and shipment lot (PRD 3.11) ────────────────────────────────────────
def quote_payload(
    design_id: str, expected_program_version: int, quoted_qty: int = 26_000, **overrides: Any
) -> Json:
    payload: Json = {
        "design_id": design_id,
        "quoted_qty": quoted_qty,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def lot_payload(run_id: str, program_id: str, piece_count: int = 1_000, **overrides: Any) -> Json:
    payload: Json = {
        "run_id": run_id,
        "program_id": program_id,
        "piece_count": piece_count,
    }
    payload.update(overrides)
    return payload


def revision_payload(expected_design_version: int, **overrides: Any) -> Json:
    payload: Json = {"expected_design_version": expected_design_version}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> Json:
    return {"to_iso8601": to_iso8601}
