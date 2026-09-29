"""Payload factories — one per PRD entity / action, request-body fields only.

Every factory's defaults form a mutually consistent "happy path": the style,
machine, fiber batch and run setup values agree with each other so that the
gauge, pile-height, pattern-repeat, denier and face-weight gates all pass.
Tests override exactly the field under test.
"""

import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def unique_code(prefix: str) -> str:
    """A per-process unique business code, for duplicate-free bulk setup."""
    return f"{prefix}-{next(_counter):04d}"


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


def create_account_payload(**overrides) -> dict:
    payload = {
        "account_code": "AC-01",
        "account_type": "DEALER",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def update_account_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PolymerLot
# ---------------------------------------------------------------------------


def create_polymer_lot_payload(**overrides) -> dict:
    payload = {
        "lot_code": "PL-VIRGIN-01",
        "polymer_type": "NYLON_66",
        "received_kg": TEST_DEFAULTS["RECEIVED_KG"],
        "melt_flow_index": TEST_DEFAULTS["MELT_FLOW_INDEX"],
        "recycled_content_pct": 0.0,
        "segregated": False,
        "reclaim_source": "VIRGIN",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReclamationBatch
# ---------------------------------------------------------------------------


def create_reclamation_batch_payload(**overrides) -> dict:
    payload = {
        "batch_code": "RB-01",
        "intake_lbs": 5000.0,
        "face_fiber_type": "NYLON_66",
        "contamination_pct": 5.0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FiberBatch
# ---------------------------------------------------------------------------


def create_fiber_batch_payload(polymer_lot_id: str, **overrides) -> dict:
    payload = {
        "batch_code": "FB-01",
        "polymer_lot_id": polymer_lot_id,
        "input_kg": TEST_DEFAULTS["INPUT_KG"],
        "denier_target": TEST_DEFAULTS["DENIER_TARGET"],
        "filament_count": TEST_DEFAULTS["FILAMENT_COUNT"],
        "dye_method": "SOLUTION_DYED",
        "solution_color_code": "SC-BEIGE-01",
    }
    payload.update(overrides)
    return payload


def extrude_fiber_batch_payload(**overrides) -> dict:
    payload = {
        "throughput_g_per_min": TEST_DEFAULTS["THROUGHPUT_G_PER_MIN"],
        "spin_speed_m_per_min": TEST_DEFAULTS["SPIN_SPEED_M_PER_MIN"],
    }
    payload.update(overrides)
    return payload


def disposition_fiber_batch_payload(disposition: str = "RELEASE", **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CarpetStyle
# ---------------------------------------------------------------------------


def create_style_payload(**overrides) -> dict:
    payload = {
        "style_code": "ST-SD-01",
        "line_type": "RUNNING_LINE",
        "gauge_code": "G_1_10",
        "pile_construction": "CUT",
        "pile_height_mm": TEST_DEFAULTS["PILE_HEIGHT_MM"],
        "pattern_repeat_mm": TEST_DEFAULTS["PATTERN_REPEAT_MM"],
        "plies": TEST_DEFAULTS["PLIES"],
        "target_face_weight_oz": TEST_DEFAULTS["TARGET_FACE_WEIGHT_OZ"],
        "dye_method": "SOLUTION_DYED",
        "solution_color_code": "SC-BEIGE-01",
        "list_price_cents_per_yard": TEST_DEFAULTS["LIST_PRICE_CENTS_PER_YARD"],
    }
    payload.update(overrides)
    return payload


def create_piece_dyed_style_payload(**overrides) -> dict:
    """A piece-dyed style: no solution_color_code, dyeing happens in a vessel."""
    payload = create_style_payload(
        style_code="ST-PD-01",
        dye_method="PIECE_DYED",
        solution_color_code=None,
    )
    payload.update(overrides)
    return payload


def discontinue_style_payload(**overrides) -> dict:
    payload = {"reason": "style runout announced"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TuftingMachine
# ---------------------------------------------------------------------------


def create_tufting_machine_payload(**overrides) -> dict:
    payload = {
        "machine_code": "TM-01",
        "native_gauge_code": "G_1_10",
        "min_pile_height_mm": TEST_DEFAULTS["MIN_PILE_HEIGHT_MM"],
        "max_pile_height_mm": TEST_DEFAULTS["MAX_PILE_HEIGHT_MM"],
        "changeover_minutes": TEST_DEFAULTS["CHANGEOVER_MINUTES"],
        "needle_bar_width_in": TEST_DEFAULTS["NEEDLE_BAR_WIDTH_IN"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DyeVessel
# ---------------------------------------------------------------------------


def create_dye_vessel_payload(**overrides) -> dict:
    payload = {
        "vessel_code": "DV-01",
        "vessel_type": "BECK",
        "capacity_kg": TEST_DEFAULTS["VESSEL_CAPACITY_KG"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ProductionRun
# ---------------------------------------------------------------------------


def create_production_run_payload(
    style_id: str, machine_id: str, fiber_batch_id: str, **overrides
) -> dict:
    payload = {
        "run_code": "PR-01",
        "style_id": style_id,
        "machine_id": machine_id,
        "fiber_batch_id": fiber_batch_id,
        "scheduled_start_utc": TEST_DEFAULTS["RUN_START_UTC"],
        "scheduled_end_utc": TEST_DEFAULTS["RUN_END_UTC"],
    }
    payload.update(overrides)
    return payload


def load_setup_payload(**overrides) -> dict:
    payload = {
        "gauge_loaded_code": "G_1_10",
        "pile_height_set_mm": TEST_DEFAULTS["PILE_HEIGHT_MM"],
        "pattern_repeat_loaded_mm": TEST_DEFAULTS["PATTERN_REPEAT_MM"],
        "stitch_rate_per_inch": TEST_DEFAULTS["STITCH_RATE_PER_INCH"],
    }
    payload.update(overrides)
    return payload


def complete_greige_payload(**overrides) -> dict:
    payload = {"greige_yards": TEST_DEFAULTS["GREIGE_YARDS"]}
    payload.update(overrides)
    return payload


def apply_backing_payload(**overrides) -> dict:
    payload = {
        "sbr_pct": TEST_DEFAULTS["SBR_PCT"],
        "filler_load_pct": TEST_DEFAULTS["FILLER_LOAD_PCT"],
        "cure_temp_c": TEST_DEFAULTS["CURE_TEMP_C"],
        "cure_seconds": TEST_DEFAULTS["CURE_SECONDS"],
        "secondary_backing_type": "ACTION_BAC",
    }
    payload.update(overrides)
    return payload


def abort_production_run_payload(**overrides) -> dict:
    payload = {"reason": "order pulled"}
    payload.update(overrides)
    return payload


def doff_roll_good_payload(**overrides) -> dict:
    payload = {
        "roll_number": "RG-01",
        "width_ft": TEST_DEFAULTS["WIDTH_FT"],
        "initial_yards": TEST_DEFAULTS["INITIAL_YARDS"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DyeLot
# ---------------------------------------------------------------------------


def create_dye_lot_payload(production_run_id: str, vessel_id: str, **overrides) -> dict:
    payload = {
        "lot_code": "DL-01",
        "production_run_id": production_run_id,
        "vessel_id": vessel_id,
        "color_code": "C-SANDSTONE",
        "target_lab_l": TEST_DEFAULTS["TARGET_LAB_L"],
        "target_lab_a": TEST_DEFAULTS["TARGET_LAB_A"],
        "target_lab_b": TEST_DEFAULTS["TARGET_LAB_B"],
        "lot_kg": TEST_DEFAULTS["LOT_KG"],
        "dye_start_utc": TEST_DEFAULTS["DYE_START_UTC"],
        "dye_end_utc": TEST_DEFAULTS["DYE_END_UTC"],
        "dyed_yards": TEST_DEFAULTS["DYED_YARDS"],
    }
    payload.update(overrides)
    return payload


def measurement_payload(expected_dye_lot_version: int, **overrides) -> dict:
    """Default reading equals the target, so delta_e is 0.00 and the band is A."""
    payload = {
        "measured_lab_l": TEST_DEFAULTS["TARGET_LAB_L"],
        "measured_lab_a": TEST_DEFAULTS["TARGET_LAB_A"],
        "measured_lab_b": TEST_DEFAULTS["TARGET_LAB_B"],
        "expected_dye_lot_version": expected_dye_lot_version,
    }
    payload.update(overrides)
    return payload


def disposition_dye_lot_payload(disposition: str = "APPROVE", **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RollGood
# ---------------------------------------------------------------------------


def qa_disposition_payload(disposition: str = "RELEASE", **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ProductTest
# ---------------------------------------------------------------------------


def create_product_test_payload(style_id: str, roll_good_id: str, **overrides) -> dict:
    payload = {
        "style_id": style_id,
        "roll_good_id": roll_good_id,
        "test_type": "FLAMMABILITY_PILL",
        "result_value": TEST_DEFAULTS["FLAMMABILITY_PASS_VALUE"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Certification
# ---------------------------------------------------------------------------


def create_certification_payload(style_id: str, source_test_ids, **overrides) -> dict:
    payload = {
        "style_id": style_id,
        "cert_type": "DOC_FF_1_70",
        "source_test_ids": list(source_test_ids),
        "expires_at_utc": TEST_DEFAULTS["CERT_EXPIRES_AT_UTC"],
    }
    payload.update(overrides)
    return payload


def revoke_certification_payload(**overrides) -> dict:
    payload = {"reason": "field complaint on the pill test specimen"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CutOrder
# ---------------------------------------------------------------------------


def create_cut_order_payload(account_id: str, style_id: str, **overrides) -> dict:
    payload = {
        "order_code": "CO-01",
        "account_id": account_id,
        "style_id": style_id,
        "order_type": "RUNNING_LINE",
        "requested_yards": TEST_DEFAULTS["REQUESTED_YARDS"],
        "shade_tolerance": "ANY",
    }
    payload.update(overrides)
    return payload


def manual_allocation_payload(
    roll_good_id: str, yards: float, expected_roll_good_version: int, **overrides
) -> dict:
    payload = {
        "roll_good_id": roll_good_id,
        "yards": yards,
        "expected_roll_good_version": expected_roll_good_version,
    }
    payload.update(overrides)
    return payload


def cancel_cut_order_payload(**overrides) -> dict:
    payload = {"reason": "buyer withdrew"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
