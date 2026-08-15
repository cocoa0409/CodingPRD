"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import DEFAULTS, WALL_DIMENSION


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "resin_index_basis": "MONTHLY_AVG",
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_profile_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "profile_code": DEFAULTS["PROFILE_CODE"],
        "critical_dimensions": [dict(WALL_DIMENSION)],
        "spc_subgroup_size": DEFAULTS["SPC_SUBGROUP_SIZE"],
        "sample_every_m": DEFAULTS["SAMPLE_EVERY_M"],
        "resin_content_kg_per_m": DEFAULTS["RESIN_CONTENT_KG_PER_M"],
        "min_line_speed_mpm": DEFAULTS["MIN_LINE_SPEED_MPM"],
        "max_line_speed_mpm": DEFAULTS["MAX_LINE_SPEED_MPM"],
    }
    defaults.update(overrides)
    return defaults


def create_die_payload(profile_id, **overrides) -> dict:
    defaults = {
        "profile_id": profile_id,
        "die_code": DEFAULTS["DIE_CODE"],
        "tooling_cost_cents": DEFAULTS["TOOLING_COST_CENTS"],
        "committed_length_m": DEFAULTS["COMMITTED_LENGTH_M"],
        "committed_weight_kg": DEFAULTS["COMMITTED_WEIGHT_KG"],
        "amortization_mode": DEFAULTS["AMORTIZATION_MODE"],
        "buffer_hours": DEFAULTS["BUFFER_HOURS"],
        "min_screw_mm": DEFAULTS["MIN_SCREW_MM"],
        "max_screw_mm": DEFAULTS["MAX_SCREW_MM"],
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": DEFAULTS["LINE_CODE"],
        "screw_diameter_mm": DEFAULTS["SCREW_DIAMETER_MM"],
    }
    defaults.update(overrides)
    return defaults


def create_resin_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_kind": "VIRGIN",
        "resin_type": DEFAULTS["BASE_RESIN_TYPE"],
        "color_family": "NATURAL",
        "received_kg": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_formulation_payload(profile_id, **overrides) -> dict:
    defaults = {
        "profile_id": profile_id,
        "formula_code": DEFAULTS["FORMULA_CODE"],
        "base_resin_type": DEFAULTS["BASE_RESIN_TYPE"],
        "color_family": DEFAULTS["COLOR_FAMILY"],
        "let_down_ratio": DEFAULTS["LET_DOWN_RATIO"],
        "max_regrind_pct": DEFAULTS["MAX_REGRIND_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_blend_batch_payload(formulation_id, virgin_lot_id, colorant_lot_id, **overrides) -> dict:
    defaults = {
        "formulation_id": formulation_id,
        "virgin_lot_id": virgin_lot_id,
        "colorant_lot_id": colorant_lot_id,
        "target_batch_kg": DEFAULTS["TARGET_BATCH_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id, profile_id, formulation_id, die_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "profile_id": profile_id,
        "formulation_id": formulation_id,
        "die_id": die_id,
        "ordered_length_m": DEFAULTS["ORDERED_LENGTH_M"],
        "cut_length_mm": DEFAULTS["CUT_LENGTH_MM"],
        "pieces_per_bundle": DEFAULTS["PIECES_PER_BUNDLE"],
        "base_unit_price_cents_per_m": DEFAULTS["BASE_UNIT_PRICE_CENTS_PER_M"],
    }
    defaults.update(overrides)
    return defaults


def create_line_assignment_payload(work_order_id, die_id, line_id, planned_start, planned_end, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "die_id": die_id,
        "line_id": line_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(assignment_id, batch_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "batch_id": batch_id,
        "line_speed_mpm": DEFAULTS["LINE_SPEED_MPM"],
    }
    defaults.update(overrides)
    return defaults


def create_spc_sample_payload(run_id, measurements, dimension_name="wall", **overrides) -> dict:
    defaults = {
        "run_id": run_id,
        "dimension_name": dimension_name,
        "measurements": measurements,
    }
    defaults.update(overrides)
    return defaults


def create_purge_event_payload(line_id, from_resin, to_resin, from_color, to_color, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "from_resin_type": from_resin,
        "to_resin_type": to_resin,
        "from_color_family": from_color,
        "to_color_family": to_color,
        "purge_grade": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_resin_index_point_payload(month, index_cents_per_kg, **overrides) -> dict:
    defaults = {"month": month, "index_cents_per_kg": index_cents_per_kg}
    defaults.update(overrides)
    return defaults
