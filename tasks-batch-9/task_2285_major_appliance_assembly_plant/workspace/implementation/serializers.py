"""Entity serializers — field lists taken verbatim from SCAFFOLD §1.1."""

import calc
from db import iso
from calc import num


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if versioned:
        out["updated_at"] = iso(rec.get("updated_at"))
        out["version"] = rec.get("version")
    return out


# --------------------------------------------------------------------------- #
def line_out(line):
    total, committed = calc.presentation_totals(line["id"])
    out = _common(line)
    out.update({
        "line_code": line["line_code"],
        "takt_seconds": line["takt_seconds"],
        "option_load_limit_pct": num(line["option_load_limit_pct"]),
        "baseline_headcount": line["baseline_headcount"],
        "current_family_code": line["current_family_code"],
        "operating_mode": line["operating_mode"],
        "stop_reason": line["stop_reason"],
        "posture": calc.line_posture(line),
        "presentation_slots_total": total,
        "presentation_slots_committed": committed,
        "free_slot_pct": num(calc.free_slot_pct(line["id"])),
        "max_released_sequence_index": calc.max_released_sequence_index(line["id"]),
        "changeover_count": line["changeover_count"],
        "checkpoint_index": line["checkpoint_index"],
    })
    return out


def station_out(station):
    out = _common(station)
    out.update({
        "line_id": station["line_id"],
        "station_code": station["station_code"],
        "position_index": station["position_index"],
        "presentation_slot_capacity": station["presentation_slot_capacity"],
        "presentation_slots_used": station["presentation_slots_used"],
        "station_cycle_seconds": station["station_cycle_seconds"],
    })
    return out


def model_variant_out(variant):
    out = _common(variant)
    out.update({
        "model_code": variant["model_code"],
        "family_code": variant["family_code"],
        "option_codes": list(variant["option_codes"]),
        "option_content_points": variant["option_content_points"],
        "labor_minutes": num(variant["labor_minutes"]),
        "requires_leak_test": variant["requires_leak_test"],
        "hipot_leakage_ma_limit": num(variant["hipot_leakage_ma_limit"]),
        "leak_limit_ml_per_min": num(variant["leak_limit_ml_per_min"]),
        "functional_cycle_count_required": variant["functional_cycle_count_required"],
        "energy_kwh_limit": num(variant["energy_kwh_limit"]),
        "water_liters_limit": num(variant["water_liters_limit"]),
        "status": variant["status"],
    })
    return out


def supplier_out(supplier):
    out = _common(supplier)
    out.update({
        "supplier_code": supplier["supplier_code"],
        "name": supplier["name"],
        "sync_window_minutes": supplier["sync_window_minutes"],
        "on_time_score": num(supplier["on_time_score"]),
        "status": supplier["status"],
        "delivered_on_time_count": supplier["delivered_on_time_count"],
        "delivered_late_count": supplier["delivered_late_count"],
        "missed_count": supplier["missed_count"],
        "quality_penalty_count": supplier["quality_penalty_count"],
    })
    return out


def part_out(part):
    out = _common(part)
    out.update({
        "part_number": part["part_number"],
        "supplier_id": part["supplier_id"],
        "is_sequenced_module": part["is_sequenced_module"],
        "line_side_max_units": part["line_side_max_units"],
        "lifecycle_status": part["lifecycle_status"],
        "service_obligation_until": iso(part["service_obligation_until"]),
        "field_failure_count": part["field_failure_count"],
        "cohort_failure_rate_per_1000": num(part["cohort_failure_rate_per_1000"]),
    })
    return out


def bom_line_out(bom_line):
    out = _common(bom_line)
    out.update({
        "model_variant_id": bom_line["model_variant_id"],
        "part_id": bom_line["part_id"],
        "station_id": bom_line["station_id"],
        "bom_position_code": bom_line["bom_position_code"],
        "qty_per_unit": num(bom_line["qty_per_unit"]),
        "effective_from_sequence": bom_line["effective_from_sequence"],
        "superseded_by_bom_line_id": bom_line["superseded_by_bom_line_id"],
        "created_by_change_id": bom_line["created_by_change_id"],
        "status": bom_line["status"],
    })
    return out


def delivery_call_out(call):
    out = _common(call)
    out.update({
        "supplier_id": call["supplier_id"],
        "part_id": call["part_id"],
        "station_id": call["station_id"],
        "window_start": iso(call["window_start"]),
        "window_end": iso(call["window_end"]),
        "sequenced_qty": call["sequenced_qty"],
        "arrived_at": iso(call["arrived_at"]),
        "lateness_minutes": call["lateness_minutes"],
        "cancel_reason": call["cancel_reason"],
        "status": call["status"],
    })
    return out


def shift_plan_out(plan):
    out = _common(plan)
    out.update({
        "line_id": plan["line_id"],
        "shift_date": plan["shift_date"],
        "shift_code": plan["shift_code"],
        "planned_headcount": plan["planned_headcount"],
        "overtime_minutes": plan["overtime_minutes"],
        "shift_start": iso(plan["shift_start"]),
        "shift_end": iso(plan["shift_end"]),
        "available_labor_minutes": num(calc.available_labor_minutes(plan)),
        "unit_labor_minutes": num(plan["unit_labor_minutes"]),
        "changeover_minutes": num(plan["changeover_minutes"]),
        "committed_labor_minutes": plan["committed_labor_minutes"],
        "status": plan["status"],
    })
    return out


def build_slot_out(slot):
    out = _common(slot)
    out.update({
        "line_id": slot["line_id"],
        "model_variant_id": slot["model_variant_id"],
        "shift_plan_id": slot["shift_plan_id"],
        "sync_delivery_call_id": slot["sync_delivery_call_id"],
        "sequence_index": slot["sequence_index"],
        "planned_start": iso(slot["planned_start"]),
        "option_points_snapshot": slot["option_points_snapshot"],
        "labor_minutes_snapshot": num(slot["labor_minutes_snapshot"]),
        "presentation_allocations": [
            {"station_id": a["station_id"], "slot_units": a["slot_units"]}
            for a in slot["presentation_allocations"]
        ],
        "allocated_slot_units": slot["allocated_slot_units"],
        "status": slot["status"],
    })
    return out


def production_unit_out(unit):
    out = _common(unit)
    out.update({
        "build_slot_id": unit["build_slot_id"],
        "serial_number": unit["serial_number"],
        "built_at_sequence_index": unit["built_at_sequence_index"],
        "assembly_status": unit["assembly_status"],
        "quality_status": unit["quality_status"],
        "rework_count": unit["rework_count"],
        "provisional_efficiency_index": num(calc.efficiency_index(unit["id"], "AS_TESTED")),
        "efficiency_index": num(unit["efficiency_index"]),
        "certification_tier": unit["certification_tier"],
    })
    return out


def quality_test_out(test):
    out = _common(test, versioned=False)
    out.update({
        "production_unit_id": test["production_unit_id"],
        "test_type": test["test_type"],
        "measured_value": num(test["measured_value"]),
        "limit_value": num(test["limit_value"]),
        "result": test["result"],
        "status": test["status"],
    })
    return out


def engineering_change_out(change):
    out = _common(change)
    out.update({
        "origin": change["origin"],
        "model_variant_id": change["model_variant_id"],
        "bom_position_code": change["bom_position_code"],
        "affected_part_id": change["affected_part_id"],
        "replacement_part_id": change["replacement_part_id"],
        "target_line_id": change["target_line_id"],
        "source_warranty_return_id": change["source_warranty_return_id"],
        "cut_in_sequence_index": change["cut_in_sequence_index"],
        "new_qty_per_unit": num(change["new_qty_per_unit"]),
        "submitted_by_user_id": change["submitted_by_user_id"],
        "decided_by_user_id": change["decided_by_user_id"],
        "revision_round": change["revision_round"],
        "cut_in_at": iso(change["cut_in_at"]),
        "status": change["status"],
    })
    return out


def warranty_return_out(ret):
    out = _common(ret)
    out.update({
        "production_unit_id": ret["production_unit_id"],
        "failure_code": ret["failure_code"],
        "field_hours": num(ret["field_hours"]),
        "returned_at": iso(ret["returned_at"]),
        "teardown_started_at": iso(ret["teardown_started_at"]),
        "disposition": ret["disposition"],
        "root_cause_part_id": ret["root_cause_part_id"],
        "engineering_change_id": ret["engineering_change_id"],
        "design_feedback_note": ret["design_feedback_note"],
        "status": ret["status"],
    })
    return out
