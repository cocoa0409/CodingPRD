"""Entity serializers — internal records hold Decimal/datetime; these convert to JSON."""

from util import fnum, iso_z


def _common(rec):
    return {
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_lot(r):
    out = {
        "id": r["id"],
        "lot_code": r["lot_code"],
        "resin_type": r["resin_type"],
        "gauge_mm": fnum(r["gauge_mm"]),
        "cleanliness_grade_required": r["cleanliness_grade_required"],
        "quantity_kg": fnum(r["quantity_kg"]),
        "unit_cost_per_kg": fnum(r["unit_cost_per_kg"]),
        "allocated_kg": fnum(r["allocated_kg"]),
        "consumed_kg": fnum(r["consumed_kg"]),
        "available_kg": fnum(r["available_kg"]),
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_batch(r):
    out = {
        "id": r["id"],
        "batch_code": r["batch_code"],
        "resin_type": r["resin_type"],
        "source_grade": r["source_grade"],
        "target_kg": fnum(r["target_kg"]),
        "accumulated_kg": fnum(r["accumulated_kg"]),
        "reserved_kg": fnum(r["reserved_kg"]),
        "consumed_kg": fnum(r["consumed_kg"]),
        "available_kg": fnum(r["available_kg"]),
        "certified_grade": r["certified_grade"],
        "max_blend_pct": (fnum(r["max_blend_pct"]) if r["max_blend_pct"] is not None else None),
        "created_by_user_id": r["created_by_user_id"],
        "decided_by_user_id": r["decided_by_user_id"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_tool(r):
    out = {
        "id": r["id"],
        "tool_code": r["tool_code"],
        "part_number": r["part_number"],
        "tool_type": r["tool_type"],
        "min_gauge_mm": fnum(r["min_gauge_mm"]),
        "max_gauge_mm": fnum(r["max_gauge_mm"]),
        "cleanliness_grade": r["cleanliness_grade"],
        "prototype_cost": fnum(r["prototype_cost"]),
        "production_cost": (fnum(r["production_cost"]) if r["production_cost"] is not None else None),
        "rated_lifetime_shots": r["rated_lifetime_shots"],
        "shots_used": r["shots_used"],
        "drawing_revision": r["drawing_revision"],
        "qualified_drawing_revision": r["qualified_drawing_revision"],
        "proto_shot_limit": r["proto_shot_limit"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_spec(r):
    out = {
        "id": r["id"],
        "spec_code": r["spec_code"],
        "spec_type": r["spec_type"],
        "cleanliness_grade": r["cleanliness_grade"],
        "per_pack_cost": fnum(r["per_pack_cost"]),
        "decided_by_user_id": r["decided_by_user_id"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_order(r):
    out = {
        "id": r["id"],
        "order_code": r["order_code"],
        "part_number": r["part_number"],
        "resin_type": r["resin_type"],
        "ordered_qty": r["ordered_qty"],
        "required_gauge_mm": fnum(r["required_gauge_mm"]),
        "cleanliness_grade": r["cleanliness_grade"],
        "is_prototype_order": r["is_prototype_order"],
        "spec_nominal_wall_mm": fnum(r["spec_nominal_wall_mm"]),
        "spec_min_wall_mm": fnum(r["spec_min_wall_mm"]),
        "nominal_part_weight_kg": fnum(r["nominal_part_weight_kg"]),
        "std_cycle_time_s": r["std_cycle_time_s"],
        "std_machine_rate_per_hour": fnum(r["std_machine_rate_per_hour"]),
        "tool_id": r["tool_id"],
        "packaging_spec_id": r["packaging_spec_id"],
        "required_material_kg": fnum(r["required_material_kg"]),
        "shots_completed": r["shots_completed"],
        "shots_scrapped": r["shots_scrapped"],
        "provisional_cost": (fnum(r["provisional_cost"]) if r["provisional_cost"] is not None else None),
        "tooling_charge": (fnum(r["tooling_charge"]) if r["tooling_charge"] is not None else None),
        "final_cost": (fnum(r["final_cost"]) if r["final_cost"] is not None else None),
        "schedule_status": r["schedule_status"],
        "quality_status": r["quality_status"],
    }
    out.update(_common(r))
    return out


def ser_allocation(r):
    out = {
        "id": r["id"],
        "production_order_id": r["production_order_id"],
        "source_type": r["source_type"],
        "lot_id": r["lot_id"],
        "regrind_batch_id": r["regrind_batch_id"],
        "qty_kg": fnum(r["qty_kg"]),
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_resource(r):
    out = {
        "id": r["id"],
        "resource_code": r["resource_code"],
        "resource_type": r["resource_type"],
        "cleanliness_grade": r["cleanliness_grade"],
        "machine_rate_per_hour": fnum(r["machine_rate_per_hour"]),
    }
    out.update(_common(r))
    return out


def ser_run(r):
    out = {
        "id": r["id"],
        "production_order_id": r["production_order_id"],
        "station_id": r["station_id"],
        "planned_start": iso_z(r["planned_start"]),
        "planned_end": iso_z(r["planned_end"]),
        "oven_temp_c": fnum(r["oven_temp_c"]),
        "cycle_time_s": r["cycle_time_s"],
        "shots_planned": r["shots_planned"],
        "shots_completed": r["shots_completed"],
        "scrap_weight_kg": (fnum(r["scrap_weight_kg"]) if r["scrap_weight_kg"] is not None else None),
        "actual_end": (iso_z(r["actual_end"]) if r["actual_end"] is not None else None),
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_scrap(r):
    # ScrapRecord: id + created_at only (PRD §2.4) — no updated_at, no version.
    return {
        "id": r["id"],
        "forming_run_id": r["forming_run_id"],
        "regrind_batch_id": r["regrind_batch_id"],
        "resin_type": r["resin_type"],
        "weight_kg": fnum(r["weight_kg"]),
        "status": r["status"],
        "created_at": r["created_at"],
    }


def ser_inspection(r):
    out = {
        "id": r["id"],
        "production_order_id": r["production_order_id"],
        "forming_run_id": r["forming_run_id"],
        "booth_id": r["booth_id"],
        "inspection_type": r["inspection_type"],
        "scheduled_start": iso_z(r["scheduled_start"]),
        "scheduled_end": iso_z(r["scheduled_end"]),
        "wall_measurements_mm": r["wall_measurements_mm"],
        "min_wall_mm": fnum(r["min_wall_mm"]),
        "avg_wall_mm": fnum(r["avg_wall_mm"]),
        "deviation_pct": fnum(r["deviation_pct"]),
        "disposition": r["disposition"],
        "scrapped_qty": r["scrapped_qty"],
        "recorded_by_user_id": r["recorded_by_user_id"],
        "dispositioned_by_user_id": r["dispositioned_by_user_id"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_task(r):
    out = {
        "id": r["id"],
        "production_order_id": r["production_order_id"],
        "task_type": r["task_type"],
        "sequence_no": r["sequence_no"],
        "insert_part_code": r["insert_part_code"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_cert(r):
    # CleanlinessCertificate: id + created_at only (PRD §2.4).
    return {
        "id": r["id"],
        "subject_type": r["subject_type"],
        "subject_id": r["subject_id"],
        "grade": r["grade"],
        "issued_at": iso_z(r["issued_at"]),
        "expires_at": iso_z(r["expires_at"]),
        "cert_body": r["cert_body"],
        "created_at": r["created_at"],
    }
