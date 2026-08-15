"""Entity serializers: internal records -> wire dictionaries (PRD 2.5/2.6)."""

from timeutil import fmt_dt, fmt_opt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def property_out(p):
    out = {
        "id": p["id"],
        "name": p["name"],
        "emergency_response_hours": p["emergency_response_hours"],
        "emergency_completion_hours": p["emergency_completion_hours"],
        "urgent_response_hours": p["urgent_response_hours"],
        "urgent_completion_hours": p["urgent_completion_hours"],
        "routine_response_hours": p["routine_response_hours"],
        "routine_completion_hours": p["routine_completion_hours"],
        "purchase_auto_approve_threshold_cents": p["purchase_auto_approve_threshold_cents"],
        "recall_window_days": p["recall_window_days"],
        "vendor_travel_buffer_minutes": p["vendor_travel_buffer_minutes"],
        "entry_notice_min_hours": p["entry_notice_min_hours"],
    }
    out.update(_common(p))
    return out


def resident_out(r):
    out = {
        "id": r["id"],
        "property_id": r["property_id"],
        "unit_number": r["unit_number"],
        "full_name": r["full_name"],
        "email": r["email"],
        "chargeback_balance_cents": r["chargeback_balance_cents"],
    }
    out.update(_common(r))
    return out


def technician_out(t):
    out = {
        "id": t["id"],
        "property_id": t["property_id"],
        "full_name": t["full_name"],
        "trade": t["trade"],
    }
    out.update(_common(t))
    return out


def vendor_out(v):
    out = {
        "id": v["id"],
        "property_id": v["property_id"],
        "company_name": v["company_name"],
        "trade": v["trade"],
        "insurance_valid_until": fmt_dt(v["insurance_valid_until"]),
        "status": v["status"],
    }
    out.update(_common(v))
    return out


def part_out(p):
    out = {
        "id": p["id"],
        "property_id": p["property_id"],
        "sku": p["sku"],
        "name": p["name"],
        "unit_cost_cents": p["unit_cost_cents"],
        "reorder_level": p["reorder_level"],
        "initial_stock": p["initial_stock"],
        "quantity_on_hand": p["quantity_on_hand"],
        "reserved_quantity": p["reserved_quantity"],
        "restock_status": p["restock_status"],
    }
    out.update(_common(p))
    return out


def work_order_out(wo):
    out = {
        "id": wo["id"],
        "property_id": wo["property_id"],
        "resident_id": wo["resident_id"],
        "unit_number": wo["unit_number"],
        "category": wo["category"],
        "priority": wo["priority"],
        "description": wo["description"],
        "status": wo["status"],
        "assignment_type": wo["assignment_type"],
        "assigned_technician_id": wo["assigned_technician_id"],
        "assigned_vendor_id": wo["assigned_vendor_id"],
        "scheduled_start_at": fmt_opt(wo["scheduled_start_at"]),
        "scheduled_end_at": fmt_opt(wo["scheduled_end_at"]),
        "entry_authorization": wo["entry_authorization"],
        "notice_posted_at": fmt_opt(wo["notice_posted_at"]),
        "first_responded_at": fmt_opt(wo["first_responded_at"]),
        "started_at": fmt_opt(wo["started_at"]),
        "completed_at": fmt_opt(wo["completed_at"]),
        "closed_at": fmt_opt(wo["closed_at"]),
        "response_due_at": fmt_dt(wo["response_due_at"]),
        "completion_due_at": fmt_dt(wo["completion_due_at"]),
        "response_sla_breached": wo["response_sla_breached"],
        "completion_sla_breached": wo["completion_sla_breached"],
        "resident_signoff": wo["resident_signoff"],
        "photo_urls": wo["photo_urls"],
        "damage_reported": wo["damage_reported"],
        "estimated_damage_cost_cents": wo["estimated_damage_cost_cents"],
        "recall_count": wo["recall_count"],
        "parts_total_cents": wo["parts_total_cents"],
    }
    out.update(_common(wo))
    return out


def work_order_part_out(w):
    out = {
        "id": w["id"],
        "work_order_id": w["work_order_id"],
        "part_id": w["part_id"],
        "quantity": w["quantity"],
        "unit_cost_cents_snapshot": w["unit_cost_cents_snapshot"],
        "line_total_cents": w["line_total_cents"],
        "status": w["status"],
    }
    out.update(_common(w))
    return out


def purchase_request_out(p):
    out = {
        "id": p["id"],
        "work_order_id": p["work_order_id"],
        "part_id": p["part_id"],
        "quantity": p["quantity"],
        "quoted_unit_cost_cents": p["quoted_unit_cost_cents"],
        "shipping_fee_cents": p["shipping_fee_cents"],
        "items_subtotal_cents": p["items_subtotal_cents"],
        "handling_fee_cents": p["handling_fee_cents"],
        "estimated_total_cents": p["estimated_total_cents"],
        "auto_approved": p["auto_approved"],
        "status": p["status"],
        "decision_reason": p["decision_reason"],
    }
    out.update(_common(p))
    return out


def chargeback_out(c):
    out = {
        "id": c["id"],
        "work_order_id": c["work_order_id"],
        "resident_id": c["resident_id"],
        "provisional_amount_cents": c["provisional_amount_cents"],
        "line_items": c["line_items"],
        "final_amount_cents": c["final_amount_cents"],
        "status": c["status"],
        "dispute_reason": c["dispute_reason"],
    }
    out.update(_common(c))
    return out
