"""Entity serializers. Output contains exactly the scaffold-declared fields plus
the common set (id, created_at, updated_at, version). Internal bookkeeping
fields (_seq, recorded_at, reviewed_at) are never serialized."""
from timeutil import fmt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt(e["created_at"]),
        "updated_at": fmt(e["updated_at"]),
        "version": e["version"],
    }


def program_view(p):
    out = _common(p)
    out.update({
        "program_year": p["program_year"],
        "season": p["season"],
        "status": p["status"],
        "hydrants_out_of_service_count": p["hydrants_out_of_service_count"],
        "unacknowledged_notification_count": p["unacknowledged_notification_count"],
    })
    return out


def zone_view(z):
    out = _common(z)
    out.update({"name": z["name"], "cooldown_minutes": z["cooldown_minutes"]})
    return out


def private_owner_view(o):
    out = _common(o)
    out.update({"name": o["name"], "contact_email": o["contact_email"]})
    return out


def hydrant_view(h):
    out = _common(h)
    out.update({
        "hydrant_number": h["hydrant_number"],
        "program_id": h["program_id"],
        "zone_id": h["zone_id"],
        "ownership": h["ownership"],
        "private_owner_id": h["private_owner_id"],
        "required_fire_flow_gpm": h["required_fire_flow_gpm"],
        "outlet_diameter_in": h["outlet_diameter_in"],
        "discharge_coefficient": h["discharge_coefficient"],
        "status": h["status"],
        "active_outage_id": h["active_outage_id"],
        "latest_inspection_id": h["latest_inspection_id"],
        "last_verified_inspection_date": fmt(h["last_verified_inspection_date"]),
        "inspection_tier": h["inspection_tier"],
        "provisional_fire_flow_gpm": h["provisional_fire_flow_gpm"],
        "approved_fire_flow_gpm": h["approved_fire_flow_gpm"],
        "targeted_flush_pending": h["targeted_flush_pending"],
    })
    return out


def inspection_view(i):
    out = _common(i)
    out.update({
        "hydrant_id": i["hydrant_id"],
        "scheduled_date": fmt(i["scheduled_date"]),
        "status": i["status"],
        "performed_date": fmt(i["performed_date"]),
        "defects_found": i["defects_found"],
        "condition_notes": i["condition_notes"],
        "performed_by_user_id": i["performed_by_user_id"],
        "verified_by_user_id": i["verified_by_user_id"],
        "result": i["result"],
    })
    return out


def flow_test_view(t):
    out = _common(t)
    out.update({
        "hydrant_id": t["hydrant_id"],
        "window_start": fmt(t["window_start"]),
        "window_end": fmt(t["window_end"]),
        "status": t["status"],
        "static_psi": t["static_psi"],
        "residual_psi": t["residual_psi"],
        "pitot_psi": t["pitot_psi"],
        "pitot_flow_gpm": t["pitot_flow_gpm"],
        "flow_at_20psi_gpm": t["flow_at_20psi_gpm"],
        "classification": t["classification"],
        "recorded_by_user_id": t["recorded_by_user_id"],
        "reviewed_by_user_id": t["reviewed_by_user_id"],
        "cancel_reason": t["cancel_reason"],
    })
    return out


def _step_view(s):
    return {
        "step_index": s["step_index"],
        "valve_tag": s["valve_tag"],
        "action": s["action"],
        "status": s["status"],
        "executed_at": fmt(s["executed_at"]),
        "executed_by_user_id": s["executed_by_user_id"],
        "flow_gpm": s["flow_gpm"],
        "duration_minutes": s["duration_minutes"],
    }


def sequence_view(s):
    out = _common(s)
    out.update({
        "program_id": s["program_id"],
        "zone_id": s["zone_id"],
        "hydrant_id": s["hydrant_id"],
        "origin": s["origin"],
        "status": s["status"],
        "window_start": fmt(s["window_start"]),
        "window_end": fmt(s["window_end"]),
        "steps": [_step_view(st) for st in s["steps"]],
        "source_chlorine_residual_mg_L": s["source_chlorine_residual_mg_L"],
        "total_flushed_gallons": s["total_flushed_gallons"],
        "dechlorination_tablets_required": s["dechlorination_tablets_required"],
        "final_discharge_residual_mg_L": s["final_discharge_residual_mg_L"],
    })
    return out


def complaint_view(c):
    out = _common(c)
    out.update({
        "hydrant_id": c["hydrant_id"],
        "category": c["category"],
        "description": c["description"],
        "status": c["status"],
        "flush_sequence_id": c["flush_sequence_id"],
    })
    return out


def outage_view(o):
    out = _common(o)
    out.update({
        "hydrant_id": o["hydrant_id"],
        "reason": o["reason"],
        "expected_return_date": fmt(o["expected_return_date"]),
        "status": o["status"],
        "notification_status": o["notification_status"],
        "notified_at": fmt(o["notified_at"]),
        "ack_deadline": fmt(o["ack_deadline"]),
        "acknowledged_at": fmt(o["acknowledged_at"]),
        "acknowledged_by_user_id": o["acknowledged_by_user_id"],
        "escalated": o["escalated"],
        "closed_at": fmt(o["closed_at"]),
    })
    return out


def _part_line_view(line):
    return {
        "part_id": line["part_id"],
        "qty": line["qty"],
        "unit_price_cents": line["unit_price_cents"],
        "status": line["status"],
    }


def work_order_view(w):
    out = _common(w)
    out.update({
        "hydrant_id": w["hydrant_id"],
        "source_inspection_id": w["source_inspection_id"],
        "description": w["description"],
        "budget_cap_cents": w["budget_cap_cents"],
        "status": w["status"],
        "part_lines": [_part_line_view(l) for l in w["part_lines"]],
        "quoted_subtotal_cents": w["quoted_subtotal_cents"],
        "quoted_discount_cents": w["quoted_discount_cents"],
        "quoted_fee_cents": w["quoted_fee_cents"],
        "quoted_total_cents": w["quoted_total_cents"],
        "actual_total_cents": w["actual_total_cents"],
        "created_by_user_id": w["created_by_user_id"],
        "approved_by_user_id": w["approved_by_user_id"],
        "last_rejection_reason": w["last_rejection_reason"],
    })
    return out


def part_view(p, available_qty):
    out = _common(p)
    out.update({
        "sku": p["sku"],
        "name": p["name"],
        "unit_price_cents": p["unit_price_cents"],
        "on_hand_qty": p["on_hand_qty"],
        "available_qty": available_qty,
    })
    return out


def iso_snapshot_view(s):
    out = _common(s)
    out.update({
        "program_id": s["program_id"],
        "weighting_profile": s["weighting_profile"],
        "status": s["status"],
        "total_hydrants_in_scope": s["total_hydrants_in_scope"],
        "flow_coverage_pct": s["flow_coverage_pct"],
        "inspection_compliance_pct": s["inspection_compliance_pct"],
        "iso_points": s["iso_points"],
        "published_at": fmt(s["published_at"]),
    })
    return out
