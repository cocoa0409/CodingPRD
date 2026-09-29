"""Entity serialisers. Derived counters are recomputed from the rows they
summarise on every read (PRD 2.11) - they are never incrementally patched."""
from decimal import Decimal

import calc
import db


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


# ---------------------------------------------------------------------------
def project(row):
    pieces = [p for p in db.store.pieces.values() if p["project_id"] == row["id"]]
    committed = 0
    for p in pieces:
        if p["allocated_cost_cents"] is not None:
            committed += int(p["allocated_cost_cents"])
    out = {
        "name": row["name"],
        "jobsite_city": row["jobsite_city"],
        "erection_start_date": row["erection_start_date"],
        "total_piece_count": len(pieces),
        "held_piece_count": len([p for p in pieces if p["qc_status"] == "HOLD"]),
        "cleared_piece_count": len(
            [p for p in pieces if p["qc_status"] in ("CLEARED", "REPAIRED")]),
        "scrapped_piece_count": len(
            [p for p in pieces if p["production_status"] == "SCRAPPED"]),
        "erected_piece_count": len(
            [p for p in pieces if p["production_status"] == "ERECTED"]),
        "committed_cost_cents": committed,
    }
    return _common(row, out)


def mix_design(row):
    out = {
        "code": row["code"],
        "strength_class": row["strength_class"],
        "design_28day_psi": row["design_28day_psi"],
        "required_release_psi": row["required_release_psi"],
        "w_c_ratio": row["w_c_ratio"],
        "cement_lb_per_cy": row["cement_lb_per_cy"],
        "unit_cost_cents_per_cy": row["unit_cost_cents_per_cy"],
        "status": row["status"],
        "suspension_reason": row["suspension_reason"],
        "qualified_at": row["qualified_at"],
    }
    return _common(row, out)


def steam_zone(row):
    out = {
        "zone_code": row["zone_code"],
        "boiler_capacity_bhp": row["boiler_capacity_bhp"],
        "therm_rate_cents_per_therm": row["therm_rate_cents_per_therm"],
    }
    return _common(row, out)


def casting_bed(row):
    committed = Decimal(0)
    cycles = 0
    for run in db.store.bed_runs.values():
        if run["bed_id"] != row["id"]:
            continue
        if run["status"] in ("TENSIONED", "CURING", "RELEASE_READY", "RELEASED"):
            committed += Decimal(run["computed_jacking_force_kips"] or 0)
        if run["status"] == "STRIPPED":
            cycles += 1
    out = {
        "bed_code": row["bed_code"],
        "steam_zone_id": row["steam_zone_id"],
        "bed_type": row["bed_type"],
        "length_ft": row["length_ft"],
        "max_strand_force_kips": row["max_strand_force_kips"],
        "turnaround_buffer_hours": row["turnaround_buffer_hours"],
        "status": row["status"],
        "committed_strand_force_kips": calc.round_half_up(committed, 2),
        "cumulative_cycle_count": cycles,
    }
    return _common(row, out)


def bed_run(row):
    piece_count = len([p for p in db.store.pieces.values()
                       if p["bed_run_id"] == row["id"]
                       and p["production_status"] != "SCRAPPED"])
    out = {
        "bed_id": row["bed_id"],
        "mix_design_id": row["mix_design_id"],
        "scheduled_start": row["scheduled_start"],
        "scheduled_end": row["scheduled_end"],
        "status": row["status"],
        "blocked_reason": row["blocked_reason"],
        "strand_count": row["strand_count"],
        "strand_diameter_in": row["strand_diameter_in"],
        "measured_elongation_in": row["measured_elongation_in"],
        "theoretical_elongation_in": row["theoretical_elongation_in"],
        "elongation_deviation_pct": row["elongation_deviation_pct"],
        "computed_jacking_force_kips": row["computed_jacking_force_kips"],
        "piece_count": piece_count,
        "cast_at": row["cast_at"],
        "released_at": row["released_at"],
        "concrete_cost_cents": row["concrete_cost_cents"],
        "strand_cost_cents": row["strand_cost_cents"],
        "energy_cost_cents": row["energy_cost_cents"],
        "form_setup_cents": row["form_setup_cents"],
        "direct_subtotal_cents": row["direct_subtotal_cents"],
        "overhead_rate_pct": row["overhead_rate_pct"],
        "overhead_cents": row["overhead_cents"],
        "total_cost_cents": row["total_cost_cents"],
    }
    return _common(row, out)


def curing_cycle(row):
    out = {
        "bed_run_id": row["bed_run_id"],
        "steam_zone_id": row["steam_zone_id"],
        "planned_start": row["planned_start"],
        "planned_end": row["planned_end"],
        "ramp_rate_f_per_hr": row["ramp_rate_f_per_hr"],
        "soak_temp_f": row["soak_temp_f"],
        "soak_hours": row["soak_hours"],
        "steam_demand_bhp": row["steam_demand_bhp"],
        "status": row["status"],
        "metered_therms": row["metered_therms"],
        "modeled_therms": row["modeled_therms"],
        "energy_therms": row["energy_therms"],
        "energy_source": row["energy_source"],
        "energy_variance_pct": row["energy_variance_pct"],
        "variance_flagged": row["variance_flagged"],
        "energy_cost_cents": row["energy_cost_cents"],
    }
    return _common(row, out)


def cylinder_set(row):
    recorded, valid = calc.cylinder_set_counts(row)
    out = {
        "bed_run_id": row["bed_run_id"],
        "purpose": row["purpose"],
        "specimen_count": row["specimen_count"],
        "cured_with_member": row["cured_with_member"],
        "cast_at": row["cast_at"],
        "status": row["status"],
        "recorded_break_count": recorded,
        "valid_break_count": valid,
        "raw_mean_psi": row["raw_mean_psi"],
        "qualified_strength_psi": row["qualified_strength_psi"],
        "strength_variant": row["strength_variant"],
        "recorded_by_user_ids": list(row["recorded_by_user_ids"]),
    }
    return _common(row, out)


def cylinder_break(row):
    out = {
        "cylinder_set_id": row["cylinder_set_id"],
        "break_at": row["break_at"],
        "age_hours": row["age_hours"],
        "load_lbf": row["load_lbf"],
        "diameter_in": row["diameter_in"],
        "computed_psi": row["computed_psi"],
        "inclusion_status": row["inclusion_status"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }
    return _common(row, out)


def piece(row):
    repair_count = len([d for d in db.store.repair_dispositions.values()
                        if d["piece_id"] == row["id"]
                        and d["status"] in ("CLOSED_ACCEPTED", "REJECTED_RECAST")])
    out = {
        "project_id": row["project_id"],
        "mix_design_id": row["mix_design_id"],
        "bed_run_id": row["bed_run_id"],
        "replaces_piece_id": row["replaces_piece_id"],
        "piece_mark": row["piece_mark"],
        "erection_sequence_no": row["erection_sequence_no"],
        "length_ft": row["length_ft"],
        "width_ft": row["width_ft"],
        "height_ft": row["height_ft"],
        "weight_lb": row["weight_lb"],
        "concrete_volume_cy": row["concrete_volume_cy"],
        "production_status": row["production_status"],
        "qc_status": row["qc_status"],
        "qc_hold_reason": row["qc_hold_reason"],
        "requires_haul_permit": row["requires_haul_permit"],
        "allocated_cost_cents": row["allocated_cost_cents"],
        "repair_count": repair_count,
    }
    return _common(row, out)


def yard_slot(row):
    weight, stacked = calc.slot_occupancy(row)
    out = {
        "slot_code": row["slot_code"],
        "bay_code": row["bay_code"],
        "capacity_weight_lb": row["capacity_weight_lb"],
        "max_stack_count": row["max_stack_count"],
        "status": calc.slot_status(row),
        "occupied_weight_lb": weight,
        "stacked_count": stacked,
    }
    return _common(row, out)


def yard_placement(row):
    out = {
        "piece_id": row["piece_id"],
        "yard_slot_id": row["yard_slot_id"],
        "stack_level": row["stack_level"],
        "placed_at": row["placed_at"],
        "released_at": row["released_at"],
        "release_reason": row["release_reason"],
        "status": row["status"],
    }
    return _common(row, out)


def haul_permit(row):
    out = {
        "project_id": row["project_id"],
        "permit_number": row["permit_number"],
        "issuing_state": row["issuing_state"],
        "max_width_ft": row["max_width_ft"],
        "max_height_ft": row["max_height_ft"],
        "max_length_ft": row["max_length_ft"],
        "max_gross_weight_lb": row["max_gross_weight_lb"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "escort_count": row["escort_count"],
        "status": row["status"],
    }
    return _common(row, out)


def shipment(row):
    metrics = calc.shipment_metrics(row)
    out = {
        "project_id": row["project_id"],
        "haul_permit_id": row["haul_permit_id"],
        "scheduled_departure": row["scheduled_departure"],
        "status": row["status"],
        "line_count": metrics["line_count"],
        "gross_weight_lb": metrics["gross_weight_lb"],
        "max_width_ft": metrics["max_width_ft"],
        "max_height_ft": metrics["max_height_ft"],
        "max_length_ft": metrics["max_length_ft"],
        "is_oversize": metrics["is_oversize"],
        "permit_fee_cents": calc.shipment_permit_fee(row),
        "dispatched_at": row["dispatched_at"],
    }
    return _common(row, out)


def shipment_line(row):
    """A ShipmentLine is written once and never modified: it carries only id
    and created_at - no updated_at and no version (PRD 2.5)."""
    ship = db.store.shipments.get(row["shipment_id"])
    surcharge = calc.line_surcharge_cents(ship, row) if ship else 0
    return {
        "id": row["id"],
        "shipment_id": row["shipment_id"],
        "piece_id": row["piece_id"],
        "load_position": row["load_position"],
        "line_surcharge_cents": surcharge,
        "loaded_at": row["loaded_at"],
        "created_at": row["created_at"],
    }


def repair_disposition(row):
    out = {
        "piece_id": row["piece_id"],
        "defect_type": row["defect_type"],
        "severity": row["severity"],
        "description": row["description"],
        "disposition": row["disposition"],
        "status": row["status"],
        "reinspection_fail_count": row["reinspection_fail_count"],
        "opened_by_user_id": row["opened_by_user_id"],
        "dispositioned_by_user_id": row["dispositioned_by_user_id"],
        "repaired_by_user_id": row["repaired_by_user_id"],
    }
    return _common(row, out)
