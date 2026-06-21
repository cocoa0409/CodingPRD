"""Entity -> JSON projections.

Each serializer emits exactly the fields the entity declares in SCAFFOLD §1.1,
including system and computed fields. Stored entities already carry their
computed values (the server reconciles them on every mutation), so serializers
are plain projections.
"""


def account_out(a):
    return {
        "id": a["id"],
        "name": a["name"],
        "billing_email": a["billing_email"],
        "standing": a["standing"],
        "outstanding_balance_cents": a["outstanding_balance_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def technician_out(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "shift_start_minute": t["shift_start_minute"],
        "shift_end_minute": t["shift_end_minute"],
        "certified_for_wells": t["certified_for_wells"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def site_out(s):
    return {
        "id": s["id"],
        "account_id": s["account_id"],
        "address": s["address"],
        "county_code": s["county_code"],
        "service_minutes": s["service_minutes"],
        "compliance_status": s["compliance_status"],
        "risk_score": s["risk_score"],
        "last_pumped_date": s["last_pumped_date"],
        "next_pump_due_date": s["next_pump_due_date"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def asset_out(a):
    return {
        "id": a["id"],
        "site_id": a["site_id"],
        "asset_type": a["asset_type"],
        "capacity_gallons": a["capacity_gallons"],
        "install_year": a["install_year"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def service_plan_out(p):
    return {
        "id": p["id"],
        "site_id": p["site_id"],
        "frequency_months": p["frequency_months"],
        "estimated_gallons": p["estimated_gallons"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def work_order_out(w):
    return {
        "id": w["id"],
        "site_id": w["site_id"],
        "route_id": w["route_id"],
        "technician_id": w["technician_id"],
        "work_type": w["work_type"],
        "scheduled_date": w["scheduled_date"],
        "window_start_minute": w["window_start_minute"],
        "estimated_gallons": w["estimated_gallons"],
        "measured_gallons": w["measured_gallons"],
        "emergency_surcharge_applies": w["emergency_surcharge_applies"],
        "status": w["status"],
        "billing_status": w["billing_status"],
        "estimated_cost_cents": w["estimated_cost_cents"],
        "final_cost_cents": w["final_cost_cents"],
        "invoice_total_cents": w["invoice_total_cents"],
        "window_end_minute": w["window_end_minute"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def route_out(r):
    return {
        "id": r["id"],
        "technician_id": r["technician_id"],
        "route_date": r["route_date"],
        "status": r["status"],
        "assigned_stop_count": r["assigned_stop_count"],
        "booked_minutes": r["booked_minutes"],
        "optimized_sequence": list(r["optimized_sequence"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def inspection_report_out(ir):
    return {
        "id": ir["id"],
        "work_order_id": ir["work_order_id"],
        "result": ir["result"],
        "defect_count": ir["defect_count"],
        "status": ir["status"],
        "finalized_at": ir["finalized_at"],
        "created_at": ir["created_at"],
        "updated_at": ir["updated_at"],
        "version": ir["version"],
    }


def permit_filing_out(pf):
    return {
        "id": pf["id"],
        "inspection_report_id": pf["inspection_report_id"],
        "site_id": pf["site_id"],
        "county_code": pf["county_code"],
        "status": pf["status"],
        "submission_count": pf["submission_count"],
        "decision_reason": pf["decision_reason"],
        "created_at": pf["created_at"],
        "updated_at": pf["updated_at"],
        "version": pf["version"],
    }


def repair_line_out(rl):
    return {
        "id": rl["id"],
        "work_order_id": rl["work_order_id"],
        "part_name": rl["part_name"],
        "quantity": rl["quantity"],
        "unit_price_cents": rl["unit_price_cents"],
        "tax_rate_bps": rl["tax_rate_bps"],
        "line_total_cents": rl["line_total_cents"],
        "created_at": rl["created_at"],
        "updated_at": rl["updated_at"],
        "version": rl["version"],
    }


def reminder_out(r):
    # Reminder is append-only: id + created_at only, plus its own fields.
    return {
        "id": r["id"],
        "site_id": r["site_id"],
        "reminder_type": r["reminder_type"],
        "due_date": r["due_date"],
        "status": r["status"],
        "created_at": r["created_at"],
    }
