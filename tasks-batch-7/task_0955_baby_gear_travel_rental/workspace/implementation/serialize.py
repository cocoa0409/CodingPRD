"""Entity serializers. created_at/updated_at rendered from internal datetimes;
internal keys (created_dt, updated_dt, _ord) never leak."""
from util import fmt_dt, fmt_clock, fmt_date


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_dt"]),
        "updated_at": fmt_dt(rec["updated_dt"]),
        "version": rec["version"],
    }


def ser_customer(c):
    return {**_base(c),
            "full_name": c["full_name"], "email": c["email"], "phone": c["phone"],
            "status": c["status"], "risk_score": c["risk_score"],
            "late_return_count": c["late_return_count"],
            "captured_damage_count": c["captured_damage_count"]}


def ser_catalog_item(i):
    return {**_base(i),
            "name": i["name"], "category": i["category"],
            "daily_rate_cents": i["daily_rate_cents"],
            "deposit_amount_cents": i["deposit_amount_cents"],
            "weight_kg": i["weight_kg"],
            "cleaning_turnaround_hours": i["cleaning_turnaround_hours"],
            "deep_clean_every_cycles": i["deep_clean_every_cycles"],
            "status": i["status"]}


def ser_unit(u):
    return {**_base(u),
            "catalog_item_id": u["catalog_item_id"],
            "serial_number": u["serial_number"],
            "condition_grade": u["condition_grade"],
            "status": u["status"],
            "cleans_since_deep": u["cleans_since_deep"],
            "blocked_until": fmt_clock(u["blocked_until"])}


def ser_partner(p):
    return {**_base(p),
            "name": p["name"], "zone_code": p["zone_code"],
            "commission_pct": p["commission_pct"], "status": p["status"]}


def ser_plan(p):
    return {**_base(p),
            "code": p["code"], "pricing_model": p["pricing_model"],
            "rate_value": p["rate_value"],
            "deductible_cents": p["deductible_cents"],
            "coverage_cap_cents": p["coverage_cap_cents"],
            "covered_severities": list(p["covered_severities"])}


def ser_reservation(r):
    return {**_base(r),
            "customer_id": r["customer_id"],
            "hotel_partner_id": r["hotel_partner_id"],
            "delivery_address": r["delivery_address"],
            "zone_code": r["zone_code"],
            "start_date": fmt_date(r["start_date"]),
            "end_date": fmt_date(r["end_date"]),
            "insurance_plan_id": r["insurance_plan_id"],
            "status": r["status"],
            "payment_status": r["payment_status"],
            "quoted_total_cents": r["quoted_total_cents"],
            "gear_subtotal_cents": r["gear_subtotal_cents"],
            "final_total_cents": r["final_total_cents"],
            "deposit_hold_cents": r["deposit_hold_cents"],
            "deposit_captured_cents": r["deposit_captured_cents"],
            "deposit_released_cents": r["deposit_released_cents"],
            "late_fee_cents": r["late_fee_cents"],
            "extension_charge_cents": r["extension_charge_cents"],
            "extension_days": r["extension_days"],
            "commission_cents": r["commission_cents"],
            "returned_at": fmt_clock(r["returned_at"])}


def ser_line(l):
    return {**_base(l),
            "reservation_id": l["reservation_id"],
            "catalog_item_id": l["catalog_item_id"],
            "assigned_unit_id": l["assigned_unit_id"],
            "status": l["status"],
            "unit_rate_cents": l["unit_rate_cents"],
            "line_charge_cents": l["line_charge_cents"]}


def ser_route(r):
    return {**_base(r),
            "route_date": fmt_date(r["route_date"]),
            "zone_code": r["zone_code"],
            "vehicle_capacity_kg": r["vehicle_capacity_kg"],
            "status": r["status"],
            "planned_weight_kg": r["planned_weight_kg"]}


def ser_stop(s):
    return {**_base(s),
            "route_id": s["route_id"],
            "reservation_id": s["reservation_id"],
            "stop_type": s["stop_type"],
            "address": s["address"],
            "time_window_start": fmt_dt(s["time_window_start_dt"]),
            "time_window_end": fmt_dt(s["time_window_end_dt"]),
            "status": s["status"],
            "sequence": s["sequence"],
            "completed_at": fmt_clock(s["completed_at"])}


def ser_extension(e):
    return {**_base(e),
            "reservation_id": e["reservation_id"],
            "requested_end_date": fmt_date(e["requested_end_date"]),
            "status": e["status"],
            "extension_charge_cents": e["extension_charge_cents"],
            "decided_by_user_id": e["decided_by_user_id"]}


def ser_claim(c):
    return {**_base(c),
            "reservation_line_id": c["reservation_line_id"],
            "severity": c["severity"],
            "repair_cost_cents": c["repair_cost_cents"],
            "description": c["description"],
            "filed_by_user_id": c["filed_by_user_id"],
            "reviewed_by_user_id": c["reviewed_by_user_id"],
            "status": c["status"],
            "capture_amount_cents": c["capture_amount_cents"]}


def ser_recall(r):
    return {**_base(r),
            "catalog_item_id": r["catalog_item_id"],
            "recall_code": r["recall_code"],
            "severity": r["severity"],
            "description": r["description"],
            "status": r["status"],
            "activated_at": fmt_clock(r["activated_at"])}


def ser_ticket(t):
    return {**_base(t),
            "unit_id": t["unit_id"],
            "ticket_type": t["ticket_type"],
            "status": t["status"],
            "inspector_user_id": t["inspector_user_id"],
            "resolution_note": t["resolution_note"]}


def ser_txn(t):
    # Ledger entry: id + created_at only, no updated_at/version.
    return {"id": t["id"],
            "created_at": fmt_dt(t["created_dt"]),
            "reservation_id": t["reservation_id"],
            "txn_type": t["txn_type"],
            "amount_cents": t["amount_cents"],
            "reason": t["reason"],
            "balance_after_cents": t["balance_after_cents"]}
