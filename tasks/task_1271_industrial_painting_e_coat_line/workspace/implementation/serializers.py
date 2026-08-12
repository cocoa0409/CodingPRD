"""Entity -> JSON payload serializers. Event records omit updated_at/version
(PRD SS2.4). Internal keys (leading underscore) are never serialized."""
from services import D, lot_outstanding


def _num(v):
    """Decimal -> float; ints pass through; floats pass through."""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    return v


def ser_customer(r):
    return {
        "id": r["id"], "name": r["name"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_spec(r):
    return {
        "id": r["id"], "customer_id": r["customer_id"], "color_code": r["color_code"],
        "film_build_min_um": _num(r["film_build_min_um"]),
        "film_build_max_um": _num(r["film_build_max_um"]),
        "cure_metal_temp_c": _num(r["cure_metal_temp_c"]),
        "cure_minutes_at_temp": r["cure_minutes_at_temp"],
        "adhesion_class_min": r["adhesion_class_min"],
        "impact_joules_min": _num(r["impact_joules_min"]),
        "voc_g_per_l": _num(r["voc_g_per_l"]),
        "area_dm2_per_part": _num(r["area_dm2_per_part"]),
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_paint_line(r):
    return {
        "id": r["id"], "name": r["name"], "current_color_code": r["current_color_code"],
        "line_speed_fpm": _num(r["line_speed_fpm"]),
        "hanger_capacity_parts": r["hanger_capacity_parts"],
        "allocation_policy": r["allocation_policy"],
        "posture": r["posture"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_cure_oven(r):
    return {
        "id": r["id"], "name": r["name"], "max_loads": r["max_loads"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_stage(r):
    return {
        "id": r["id"], "paint_line_id": r["paint_line_id"], "stage_name": r["stage_name"],
        "sequence_no": r["sequence_no"], "chemical_family": r["chemical_family"],
        "conc_min_gpl": _num(r["conc_min_gpl"]), "conc_max_gpl": _num(r["conc_max_gpl"]),
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_titration(r):
    return {
        "id": r["id"], "stage_id": r["stage_id"],
        "measured_conc_gpl": _num(r["measured_conc_gpl"]),
        "recorded_by_user_id": r["recorded_by_user_id"],
        "in_range": r["in_range"],
        "created_at": r["created_at"],
    }


def ser_lot(r):
    return {
        "id": r["id"], "customer_id": r["customer_id"], "spec_id": r["spec_id"],
        "part_quantity": r["part_quantity"],
        "scrapped_quantity": r["scrapped_quantity"],
        "passed_quantity": r["passed_quantity"],
        "outstanding_quantity": lot_outstanding(r),
        "rework_count": r["rework_count"],
        "status": r["status"],
        "base_charge_cents": r["base_charge_cents"],
        "purge_alloc_cents": r["purge_alloc_cents"],
        "rework_charge_cents": r["rework_charge_cents"],
        "total_charge_cents": r["total_charge_cents"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_run_slot(r):
    return {
        "id": r["id"], "paint_line_id": r["paint_line_id"], "lot_id": r["lot_id"],
        "start_utc": r["start_utc"], "end_utc": r["end_utc"],
        "parts_per_hanger": r["parts_per_hanger"],
        "planned_line_speed_fpm": _num(r["planned_line_speed_fpm"]),
        "predicted_film_build_um": _num(r["predicted_film_build_um"]),
        "voc_projected_kg": _num(r["voc_projected_kg"]),
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_oven_cycle(r):
    return {
        "id": r["id"], "lot_id": r["lot_id"], "oven_id": r["oven_id"],
        "recheck_of_id": r["recheck_of_id"],
        "entered_at": r["entered_at"], "exited_at": r["exited_at"],
        "min_metal_temp_c": _num(r["min_metal_temp_c"]),
        "minutes_at_or_above_temp": r["minutes_at_or_above_temp"],
        "verdict": r["verdict"],
        "created_at": r["created_at"],
    }


def ser_quality_test(r):
    return {
        "id": r["id"], "lot_id": r["lot_id"], "test_type": r["test_type"],
        "measured_value": _num(r["measured_value"]),
        "recorded_by_user_id": r["recorded_by_user_id"],
        "verdict": r["verdict"],
        "created_at": r["created_at"],
    }


def ser_rework_order(r):
    return {
        "id": r["id"], "lot_id": r["lot_id"],
        "parts_to_rework": r["parts_to_rework"],
        "status": r["status"],
        "strip_cost_cents": r["strip_cost_cents"],
        "repaint_charge_cents": r["repaint_charge_cents"],
        "scrapped_quantity": r["scrapped_quantity"],
        "total_charge_cents": r["total_charge_cents"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_color_change(r):
    return {
        "id": r["id"], "paint_line_id": r["paint_line_id"],
        "from_color_code": r["from_color_code"], "to_color_code": r["to_color_code"],
        "window_start_utc": r["window_start_utc"], "window_end_utc": r["window_end_utc"],
        "purge_solvent_liters": _num(r["purge_solvent_liters"]),
        "purge_cost_cents": r["purge_cost_cents"],
        "purge_voc_kg": _num(r["purge_voc_kg"]),
        "allocation_method": r["allocation_method"],
        "created_at": r["created_at"],
    }


def ser_voc_permit(r):
    return {
        "id": r["id"], "period_start": r["period_start"], "period_end": r["period_end"],
        "cap_kg": _num(r["cap_kg"]),
        "used_kg": _num(r["_used_kg"]),
        "reserved_kg": _num(r["_reserved_kg"]),
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_emission_entry(r):
    return {
        "id": r["id"], "permit_id": r["permit_id"],
        "source_type": r["source_type"],
        "source_lot_id": r["source_lot_id"],
        "source_color_change_id": r["source_color_change_id"],
        "voc_kg": _num(r["voc_kg"]),
        "entry_variant": r["entry_variant"],
        "created_at": r["created_at"],
    }
