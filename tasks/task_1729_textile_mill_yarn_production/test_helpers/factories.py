"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import uuid

from .constants import (
    DEFAULT_CENTROID_A,
    DEFAULT_CENTROID_B,
    DEFAULT_CENTROID_L,
    DEFAULT_DELTA_E_TOLERANCE,
    DEFAULT_SCHEDULED_AT,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)


def _unique_code(prefix: str) -> str:
    """Unique human-readable code for recipe_code / machine_code payloads."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_fiber_lot_payload(**overrides) -> dict:
    defaults = {
        "fiber_type": "COTTON",
        "received_weight_lbs": 500.0,
        "unit_cost_per_lb": 1.5,
    }
    defaults.update(overrides)
    return defaults


def create_blend_recipe_payload(**overrides) -> dict:
    defaults = {
        "recipe_code": _unique_code("REC"),
        "target_yarn_count_ne": 20.0,
    }
    defaults.update(overrides)
    return defaults


def add_blend_component_payload(fiber_lot_id, component_weight_lbs=100.0) -> dict:
    return {
        "fiber_lot_id": fiber_lot_id,
        "component_weight_lbs": component_weight_lbs,
    }


def create_spinning_machine_payload(**overrides) -> dict:
    defaults = {
        "machine_code": _unique_code("SPIN"),
        "supported_count_min_ne": 10.0,
        "supported_count_max_ne": 30.0,
    }
    defaults.update(overrides)
    return defaults


def create_yarn_lot_payload(recipe_id, **overrides) -> dict:
    defaults = {
        "recipe_id": recipe_id,
        "spun_weight_lbs": 180.0,
        "actual_yarn_count_ne": 20.0,
    }
    defaults.update(overrides)
    return defaults


def create_machine_assignment_payload(machine_id, yarn_lot_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "yarn_lot_id": yarn_lot_id,
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_shade_band_payload(**overrides) -> dict:
    defaults = {
        "customer_code": "ACME",
        "color_code": "NAVY-2B",
        "centroid_l": DEFAULT_CENTROID_L,
        "centroid_a": DEFAULT_CENTROID_A,
        "centroid_b": DEFAULT_CENTROID_B,
        "delta_e_tolerance": DEFAULT_DELTA_E_TOLERANCE,
    }
    defaults.update(overrides)
    return defaults


def create_lab_dip_payload(shade_band_id, **overrides) -> dict:
    defaults = {
        "shade_band_id": shade_band_id,
        "measured_delta_e": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_dye_lot_payload(yarn_lot_id, shade_band_id, **overrides) -> dict:
    defaults = {
        "yarn_lot_id": yarn_lot_id,
        "shade_band_id": shade_band_id,
        "vat_id": "VAT-01",
        "scheduled_at": DEFAULT_SCHEDULED_AT,
        "requested_yards": 5000.0,
    }
    defaults.update(overrides)
    return defaults


def create_quality_test_payload(**overrides) -> dict:
    defaults = {
        "shrinkage_pct_provisional": 3.0,
        "hand_score": 5,
    }
    defaults.update(overrides)
    return defaults


def create_finished_roll_payload(dye_lot_id, **overrides) -> dict:
    defaults = {
        "dye_lot_id": dye_lot_id,
        "put_up_yards": 1000.0,
        "actual_yards": 1000.0,
    }
    defaults.update(overrides)
    return defaults


def create_customer_order_payload(**overrides) -> dict:
    defaults = {
        "customer_code": "ACME",
        "color_code": "NAVY-2B",
        "requested_yards": 5000.0,
    }
    defaults.update(overrides)
    return defaults
