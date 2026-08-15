"""Entity serializers — convert internal records (Decimal-safe) into JSON dicts.

Common fields per PRD §2.4: id, created_at, updated_at, version on every
primary resource EXCEPT BlendComponent, which carries only id and created_at
(components are detached and re-derived, never updated in place).
"""

from validators import to_number


def _num(record, key):
    v = record.get(key)
    if v is None:
        return None
    return to_number(v)


def serialize_fiber_lot(r):
    return {
        "id": r["id"],
        "fiber_type": r["fiber_type"],
        "received_weight_lbs": _num(r, "received_weight_lbs"),
        "available_weight_lbs": _num(r, "available_weight_lbs"),
        "unit_cost_per_lb": _num(r, "unit_cost_per_lb"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_blend_recipe(r):
    return {
        "id": r["id"],
        "recipe_code": r["recipe_code"],
        "target_yarn_count_ne": _num(r, "target_yarn_count_ne"),
        "status": r["status"],
        "total_component_weight_lbs": _num(r, "total_component_weight_lbs"),
        "projected_cost_per_lb": _num(r, "projected_cost_per_lb"),
        "approved_at": r.get("approved_at"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_blend_component(r):
    return {
        "id": r["id"],
        "recipe_id": r["recipe_id"],
        "fiber_lot_id": r["fiber_lot_id"],
        "component_weight_lbs": _num(r, "component_weight_lbs"),
        "proportion_pct": _num(r, "proportion_pct"),
        "created_at": r["created_at"],
    }


def serialize_spinning_machine(r):
    return {
        "id": r["id"],
        "machine_code": r["machine_code"],
        "supported_count_min_ne": _num(r, "supported_count_min_ne"),
        "supported_count_max_ne": _num(r, "supported_count_max_ne"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_yarn_lot(r):
    return {
        "id": r["id"],
        "recipe_id": r["recipe_id"],
        "spun_weight_lbs": _num(r, "spun_weight_lbs"),
        "actual_yarn_count_ne": _num(r, "actual_yarn_count_ne"),
        "greige_yards_available": _num(r, "greige_yards_available"),
        "actual_cost_per_lb": _num(r, "actual_cost_per_lb"),
        "status": r["status"],
        "count_deviation_flag": bool(r.get("count_deviation_flag", False)),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_machine_assignment(r):
    return {
        "id": r["id"],
        "machine_id": r["machine_id"],
        "yarn_lot_id": r["yarn_lot_id"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_dye_lot(r):
    return {
        "id": r["id"],
        "yarn_lot_id": r["yarn_lot_id"],
        "shade_band_id": r["shade_band_id"],
        "vat_id": r["vat_id"],
        "scheduled_at": r["scheduled_at"],
        "requested_yards": _num(r, "requested_yards"),
        "status": r["status"],
        "measured_delta_e": _num(r, "measured_delta_e"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_shade_band(r):
    return {
        "id": r["id"],
        "customer_code": r["customer_code"],
        "color_code": r["color_code"],
        "centroid_l": _num(r, "centroid_l"),
        "centroid_a": _num(r, "centroid_a"),
        "centroid_b": _num(r, "centroid_b"),
        "delta_e_tolerance": _num(r, "delta_e_tolerance"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_lab_dip(r):
    return {
        "id": r["id"],
        "shade_band_id": r["shade_band_id"],
        "submitted_by_operator_id": r["submitted_by_operator_id"],
        "measured_delta_e": _num(r, "measured_delta_e"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_quality_test(r):
    return {
        "id": r["id"],
        "dye_lot_id": r["dye_lot_id"],
        "shrinkage_pct_provisional": _num(r, "shrinkage_pct_provisional"),
        "shrinkage_pct_final": _num(r, "shrinkage_pct_final"),
        "hand_score": r["hand_score"],
        "grade": r["grade"],
        "measured_l": _num(r, "measured_l"),
        "measured_a": _num(r, "measured_a"),
        "measured_b": _num(r, "measured_b"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_finished_roll(r):
    return {
        "id": r["id"],
        "dye_lot_id": r["dye_lot_id"],
        "put_up_yards": _num(r, "put_up_yards"),
        "actual_yards": _num(r, "actual_yards"),
        "yardage_deviation_pct": _num(r, "yardage_deviation_pct"),
        "is_second_quality": bool(r.get("is_second_quality", False)),
        "allocated_order_id": r.get("allocated_order_id"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_customer_order(r):
    return {
        "id": r["id"],
        "customer_code": r["customer_code"],
        "color_code": r["color_code"],
        "requested_yards": _num(r, "requested_yards"),
        "allocated_yards": _num(r, "allocated_yards"),
        "yardage_tolerance_pct": _num(r, "yardage_tolerance_pct"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
