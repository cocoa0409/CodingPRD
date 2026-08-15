"""Serializers: entity dict -> API output dict (JSON-safe, correct field set)."""

from services.core import dt_iso


def serialize_line(line):
    return {
        "id": line["id"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
        "line_code": line["line_code"],
        "line_type": line["line_type"],
        "rated_speed_bpm": line["rated_speed_bpm"],
    }


def serialize_shift(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "shift_date": s["shift_date"],
        "shift_code": s["shift_code"],
        "shackle_capacity_birds": s["shackle_capacity_birds"],
        "labor_hours_budget": s["labor_hours_budget"],
        "shacklers_present": s["shacklers_present"],
        "eviscerators_present": s["eviscerators_present"],
        "deboners_present": s["deboners_present"],
        "qa_techs_present": s["qa_techs_present"],
        "status": s["status"],
        "suspend_reason": s["suspend_reason"],
        "process_water_gallons": s["process_water_gallons"],
        "chiller_water_gallons": s["chiller_water_gallons"],
        "birds_processed": s["birds_processed"],
        "chilled_weight_lb": s["chilled_weight_lb"],
        "water_rate_birds_basis": s["water_rate_birds_basis"],
        "water_rate_weight_basis": s["water_rate_weight_basis"],
        "water_breach_active": s["water_breach_active"],
        "chiller_limit_breached": s["chiller_limit_breached"],
        "labor_hours_remaining": s["labor_hours_remaining"],
        "started_at": dt_iso(s.get("started_at")),
        "closed_at": dt_iso(s.get("closed_at")),
    }


def serialize_sanitation_run(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "shift_id": r["shift_id"],
        "line_id": r["line_id"],
        "window_start": dt_iso(r["window_start"]),
        "window_end": dt_iso(r["window_end"]),
        "status": r["status"],
        "completer_user_id": r.get("completer_user_id"),
        "verifier_user_id": r.get("verifier_user_id"),
    }


def serialize_preop(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "shift_id": p["shift_id"],
        "line_id": p["line_id"],
        "status": p["status"],
        "findings": p.get("findings"),
        "inspector_user_id": p.get("inspector_user_id"),
        "cycle_count": p["cycle_count"],
    }


def serialize_waiver(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "line_id": w["line_id"],
        "max_speed_bpm": w["max_speed_bpm"],
        "effective_from": dt_iso(w["effective_from"]),
        "effective_to": dt_iso(w["effective_to"]),
        "status": w["status"],
        "denial_count": w["denial_count"],
        "approved_by": w.get("approved_by"),
    }


def serialize_flock_lot(lot):
    return {
        "id": lot["id"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
        "lot_code": lot["lot_code"],
        "grower_name": lot["grower_name"],
        "booked_head_count": lot["booked_head_count"],
        "expected_avg_live_weight_lb": lot["expected_avg_live_weight_lb"],
        "receiving_shift_id": lot["receiving_shift_id"],
        "status": lot["status"],
        "head_count_received": lot.get("head_count_received"),
        "doa_count": lot.get("doa_count"),
        "total_live_weight_lb": lot.get("total_live_weight_lb"),
        "birds_hung_total": lot["birds_hung_total"],
        "condemned_accounted": lot["condemned_accounted"],
        "carcasses_to_chill": lot["carcasses_to_chill"],
        "carcass_weight_total_lb": lot["carcass_weight_total_lb"],
        "provisional_yield_pct": lot.get("provisional_yield_pct"),
        "certified_yield_pct": lot.get("certified_yield_pct"),
        "settled_at": dt_iso(lot.get("settled_at")),
    }


def serialize_line_run(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "shift_id": r["shift_id"],
        "line_id": r["line_id"],
        "flock_lot_id": r["flock_lot_id"],
        "planned_speed_bpm": r["planned_speed_bpm"],
        "current_speed_bpm": r.get("current_speed_bpm"),
        "speed_clamped": r["speed_clamped"],
        "status": r["status"],
        "birds_hung": r.get("birds_hung"),
        "carcass_weight_lb": r.get("carcass_weight_lb"),
        "auto_paused": r["auto_paused"],
        "started_at": dt_iso(r.get("started_at")),
        "completed_at": dt_iso(r.get("completed_at")),
    }


def serialize_condemnation(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "line_run_id": c["line_run_id"],
        "condemnation_code": c["condemnation_code"],
        "carcass_count": c["carcass_count"],
        "amended_carcass_count": c.get("amended_carcass_count"),
        "effective_count": c.get("effective_count"),
        "recorded_by_user_id": c["recorded_by_user_id"],
        "certified_by_user_id": c.get("certified_by_user_id"),
        "status": c["status"],
    }


def serialize_utility_reading(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "shift_id": r["shift_id"],
        "meter_type": r["meter_type"],
        "gallons": r["gallons"],
        "recorded_at": dt_iso(r["recorded_at"]),
    }


def serialize_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "customer_name": o["customer_name"],
        "product_code": o["product_code"],
        "pounds_ordered": o["pounds_ordered"],
        "temperature_requirement": o["temperature_requirement"],
        "due_at": dt_iso(o["due_at"]),
        "fulfillment_status": o["fulfillment_status"],
        "allocation_status": o["allocation_status"],
        "filled_lb": o["filled_lb"],
    }


def serialize_batch(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "order_id": b["order_id"],
        "flock_lot_id": b["flock_lot_id"],
        "shift_id": b["shift_id"],
        "line_id": b["line_id"],
        "crew_count": b["crew_count"],
        "input_weight_lb": b["input_weight_lb"],
        "estimated_labor_hours": b["estimated_labor_hours"],
        "actual_output_weight_lb": b.get("actual_output_weight_lb"),
        "actual_labor_hours": b.get("actual_labor_hours"),
        "net_weight_lb": b.get("net_weight_lb"),
        "status": b["status"],
    }


def serialize_finished_lot(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "deboning_batch_id": f["deboning_batch_id"],
        "order_id": f["order_id"],
        "trace_code": f["trace_code"],
        "net_weight_lb": f["net_weight_lb"],
        "routing_status": f["routing_status"],
        "status": f["status"],
        "locked_at": dt_iso(f.get("locked_at")),
        "shipped_at": dt_iso(f.get("shipped_at")),
    }


def serialize_chill_log(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "finished_lot_id": c["finished_lot_id"],
        "location": c["location"],
        "temperature_c": c["temperature_c"],
        "recorded_at": dt_iso(c["recorded_at"]),
    }
