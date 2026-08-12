"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["CUSTOMER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_coating_spec_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "color_code": TEST_DEFAULTS["COLOR_RAL9005"],
        "film_build_min_um": TEST_DEFAULTS["SPEC_FILM_MIN_UM"],
        "film_build_max_um": TEST_DEFAULTS["SPEC_FILM_MAX_UM"],
        "cure_metal_temp_c": TEST_DEFAULTS["SPEC_CURE_METAL_TEMP_C"],
        "cure_minutes_at_temp": TEST_DEFAULTS["SPEC_CURE_MINUTES_AT_TEMP"],
        "adhesion_class_min": TEST_DEFAULTS["SPEC_ADHESION_CLASS_MIN"],
        "impact_joules_min": TEST_DEFAULTS["SPEC_IMPACT_JOULES_MIN"],
        "voc_g_per_l": TEST_DEFAULTS["SPEC_VOC_G_PER_L"],
        "area_dm2_per_part": TEST_DEFAULTS["SPEC_AREA_DM2_PER_PART"],
    }
    defaults.update(overrides)
    return defaults


def create_paint_line_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["LINE_NAME"],
        "current_color_code": TEST_DEFAULTS["COLOR_RAL9005"],
        "line_speed_fpm": TEST_DEFAULTS["LINE_SPEED_FPM"],
        "hanger_capacity_parts": TEST_DEFAULTS["HANGER_CAPACITY_PARTS"],
        "allocation_policy": "FULL_TO_NEXT_LOT",
    }
    defaults.update(overrides)
    return defaults


def create_cure_oven_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["OVEN_NAME"],
        "max_loads": TEST_DEFAULTS["OVEN_MAX_LOADS"],
    }
    defaults.update(overrides)
    return defaults


def create_pretreatment_stage_payload(paint_line_id, **overrides) -> dict:
    defaults = {
        "paint_line_id": paint_line_id,
        "stage_name": TEST_DEFAULTS["STAGE_NAME"],
        "sequence_no": 1,
        "chemical_family": TEST_DEFAULTS["CHEMICAL_FAMILY"],
        "conc_min_gpl": TEST_DEFAULTS["CONC_MIN_GPL"],
        "conc_max_gpl": TEST_DEFAULTS["CONC_MAX_GPL"],
    }
    defaults.update(overrides)
    return defaults


def create_titration_reading_payload(stage_id, **overrides) -> dict:
    defaults = {
        "stage_id": stage_id,
        "measured_conc_gpl": 25.0,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(**overrides) -> dict:
    defaults = {"chemical_added_kg": 1.0}
    defaults.update(overrides)
    return defaults


def create_lot_payload(customer_id, spec_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "spec_id": spec_id,
        "part_quantity": TEST_DEFAULTS["PART_QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def create_run_slot_payload(paint_line_id, lot_id, expected_paint_line_version, **overrides) -> dict:
    defaults = {
        "paint_line_id": paint_line_id,
        "lot_id": lot_id,
        "start_utc": TEST_DEFAULTS["SLOT_START_UTC"],
        "end_utc": TEST_DEFAULTS["SLOT_END_UTC"],
        "parts_per_hanger": TEST_DEFAULTS["PARTS_PER_HANGER"],
        "expected_paint_line_version": expected_paint_line_version,
    }
    defaults.update(overrides)
    return defaults


def create_complete_slot_payload(**overrides) -> dict:
    defaults = {"paint_used_liters": TEST_DEFAULTS["PAINT_USED_LITERS"]}
    defaults.update(overrides)
    return defaults


def create_oven_cycle_payload(lot_id, oven_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "oven_id": oven_id,
        "entered_at": "2026-05-05T10:05:00Z",
        "exited_at": "2026-05-05T10:45:00Z",
        "min_metal_temp_c": 182.0,
        "minutes_at_or_above_temp": 22,
    }
    defaults.update(overrides)
    return defaults


def create_quality_test_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "test_type": "ADHESION",
        "measured_value": 3,
    }
    defaults.update(overrides)
    return defaults


def create_complete_strip_payload(**overrides) -> dict:
    defaults = {"scrapped_quantity": 0}
    defaults.update(overrides)
    return defaults


def create_color_change_payload(paint_line_id, **overrides) -> dict:
    defaults = {
        "paint_line_id": paint_line_id,
        "to_color_code": TEST_DEFAULTS["COLOR_RAL1018"],
        "purge_solvent_liters": 1.0,
        "window_start_utc": "2026-05-06T08:00:00Z",
        "window_end_utc": "2026-05-06T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_voc_permit_payload(**overrides) -> dict:
    defaults = {
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
        "cap_kg": TEST_DEFAULTS["PERMIT_CAP_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_clock_set_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
