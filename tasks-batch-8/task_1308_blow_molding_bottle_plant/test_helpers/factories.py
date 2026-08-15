"""Payload factories — one per entity, input fields only (PRD section 3/4)."""
from .constants import MAIN_TIERS


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Bev",
        "customer_code": "ACME",
        "credit_limit_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_freight_rate_card_payload(**overrides) -> dict:
    defaults = {
        "lane_code": "MAIN",
        "tiers": list(MAIN_TIERS),
    }
    defaults.update(overrides)
    return defaults


def create_machine_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": "L1",
        "has_inline_labeler": True,
        "max_bottle_diameter_mm": 120,
        "resident_volume_kg": 50,
    }
    defaults.update(overrides)
    return defaults


def create_mold_payload(**overrides) -> dict:
    defaults = {
        "mold_code": "M8",
        "base_cavities": 8,
        "compatible_resins": ["PET"],
        "reference_weight_g": 20,
    }
    defaults.update(overrides)
    return defaults


def create_bottle_spec_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "spec_code": "B500",
        "resin_type": "PET",
        "color_contrast_class": "CLEAR",
        "target_weight_g": 22,
        "weight_tolerance_pct": 2.0,
        "neck_finish": "PCO1881",
        "height_mm": 210,
        "diameter_mm": 66,
        "bottle_cube_cm3": 4000,
        "preform_cube_cm3": 150,
        "preform_weight_g": 22,
        "unit_price_cents": 9,
        "label_type": "PRESSURE_SENSITIVE",
        "min_cavitation_required": 4,
    }
    defaults.update(overrides)
    return defaults


def create_qualification_run_payload(bottle_spec_id, expected_bottle_spec_version,
                                     sample_cavity_count=8, **overrides) -> dict:
    defaults = {
        "bottle_spec_id": bottle_spec_id,
        "sample_cavity_count": sample_cavity_count,
        "expected_bottle_spec_version": expected_bottle_spec_version,
    }
    defaults.update(overrides)
    return defaults


def execute_qualification_run_payload(measured_mean_weight_g=22.1,
                                      weight_spread_g=0.4,
                                      visual_defects=0, **overrides) -> dict:
    defaults = {
        "measured_mean_weight_g": measured_mean_weight_g,
        "weight_spread_g": weight_spread_g,
        "visual_defects": visual_defects,
    }
    defaults.update(overrides)
    return defaults


def review_qualification_run_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_cavity_blockout_payload(cavity_index, reason, expected_mold_version,
                                   **overrides) -> dict:
    defaults = {
        "cavity_index": cavity_index,
        "reason": reason,
        "expected_mold_version": expected_mold_version,
    }
    defaults.update(overrides)
    return defaults


def create_material_lot_payload(**overrides) -> dict:
    defaults = {
        "material_type": "RESIN",
        "resin_type": "PET",
        "lot_code": "R-100",
        "received_kg": 500,
    }
    defaults.update(overrides)
    # PRD §3.4: "a resin lot must name its `resin_type` ... and carries no
    # `color_code`, while a colorant lot must name its `color_code` and
    # carries no `resin_type`." Drop the cross-field for the resolved
    # material_type unless the caller explicitly supplied it (negative tests).
    if defaults.get("material_type") == "COLORANT" and "resin_type" not in overrides:
        defaults.pop("resin_type", None)
    if defaults.get("material_type") == "RESIN" and "color_code" not in overrides:
        defaults.pop("color_code", None)
    return defaults


def create_production_order_payload(bottle_spec_id, **overrides) -> dict:
    defaults = {
        "bottle_spec_id": bottle_spec_id,
        "quantity_ordered": 3000,
        "planned_weight_g": 22,
    }
    defaults.update(overrides)
    return defaults


def schedule_order_payload(machine_line_id, planned_start, planned_end,
                           expected_production_order_version, **overrides) -> dict:
    defaults = {
        "machine_line_id": machine_line_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "expected_production_order_version": expected_production_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(production_order_id, machine_line_id, mold_id,
                                  material_lot_id, **overrides) -> dict:
    defaults = {
        "production_order_id": production_order_id,
        "machine_line_id": machine_line_id,
        "mold_id": mold_id,
        "material_lot_id": material_lot_id,
    }
    defaults.update(overrides)
    return defaults


def close_production_run_payload(cycles_completed=2000, good_count=11880,
                                 scrap_count=120, actual_drawdown_kg=360.0,
                                 **overrides) -> dict:
    defaults = {
        "cycles_completed": cycles_completed,
        "good_count": good_count,
        "scrap_count": scrap_count,
        "actual_drawdown_kg": actual_drawdown_kg,
    }
    defaults.update(overrides)
    return defaults


def record_results_payload(leak_failures, drop_failures, **overrides) -> dict:
    defaults = {
        "leak_failures": leak_failures,
        "drop_failures": drop_failures,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(production_order_id, quantity,
                            shipment_mode="FINISHED_BOTTLES", **overrides) -> dict:
    defaults = {
        "production_order_id": production_order_id,
        "quantity": quantity,
        "shipment_mode": shipment_mode,
    }
    defaults.update(overrides)
    return defaults


def create_dock_appointment_payload(shipment_id, dock_door, window_start,
                                    window_end, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "dock_door": dock_door,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_freight_quote_payload(bottle_spec_id, quantity,
                                 shipment_mode="FINISHED_BOTTLES", **overrides) -> dict:
    defaults = {
        "bottle_spec_id": bottle_spec_id,
        "quantity": quantity,
        "shipment_mode": shipment_mode,
    }
    defaults.update(overrides)
    return defaults
