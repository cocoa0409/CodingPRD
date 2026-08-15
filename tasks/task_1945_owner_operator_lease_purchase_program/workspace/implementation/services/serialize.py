"""Entity serializers: strip internal underscore fields, format datetimes."""

from util import fmt_dt


def serialize_operator(o):
    return {
        "id": o["id"],
        "legal_name": o["legal_name"],
        "cdl_number": o["cdl_number"],
        "classification_status": o["classification_status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_truck(t):
    return {
        "id": t["id"],
        "vin": t["vin"],
        "year": t["year"],
        "make": t["make"],
        "model": t["model"],
        "odometer_current": t["odometer_current"],
        "powertrain_warranty_expires_on": fmt_dt(t["_warranty_expires_on"]),
        "powertrain_warranty_mileage_limit": t["powertrain_warranty_mileage_limit"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_lease(l):
    return {
        "id": l["id"],
        "owner_operator_id": l["owner_operator_id"],
        "truck_id": l["truck_id"],
        "start_date": fmt_dt(l["_start_date"]),
        "term_weeks": l["term_weeks"],
        "weekly_payment_cents": l["weekly_payment_cents"],
        "escrow_weekly_contribution_cents": l["escrow_weekly_contribution_cents"],
        "escrow_cap_cents": l["escrow_cap_cents"],
        "buyout_base_price_cents": l["buyout_base_price_cents"],
        "min_revenue_guarantee_weekly_cents": l["min_revenue_guarantee_weekly_cents"],
        "status": l["status"],
        "missed_payment_count": l["missed_payment_count"],
        "arrears_cents": l["arrears_cents"],
        "total_payments_applied_cents": l["total_payments_applied_cents"],
        "escrow_satisfied": l["escrow_satisfied"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_escrow(e):
    return {
        "id": e["id"],
        "lease_id": e["lease_id"],
        "balance_cents": e["balance_cents"],
        "total_credited_cents": e["total_credited_cents"],
        "total_refunded_cents": e["total_refunded_cents"],
        "total_applied_cents": e["total_applied_cents"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_settlement(s):
    return {
        "id": s["id"],
        "lease_id": s["lease_id"],
        "week_start_date": fmt_dt(s["_week_start_date"]),
        "gross_revenue_cents": s["gross_revenue_cents"],
        "fuel_gallons": s["fuel_gallons"],
        "fuel_price_cents_per_gallon": s["fuel_price_cents_per_gallon"],
        "insurance_weekly_cents": s["insurance_weekly_cents"],
        "miles_driven": s["miles_driven"],
        "load_declined_flag": s["load_declined_flag"],
        "fuel_deduction_cents": s["fuel_deduction_cents"],
        "maintenance_deduction_cents": s["maintenance_deduction_cents"],
        "guarantee_top_up_cents": s["guarantee_top_up_cents"],
        "escrow_contribution_cents": s["escrow_contribution_cents"],
        "lease_payment_applied_cents": s["lease_payment_applied_cents"],
        "payment_short_flag": s["payment_short_flag"],
        "net_pay_cents": s["net_pay_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_lane(l):
    return {
        "id": l["id"],
        "lease_id": l["lease_id"],
        "origin": l["origin"],
        "destination": l["destination"],
        "weekly_commitment_cents": l["weekly_commitment_cents"],
        "start_date": fmt_dt(l["_start_date"]),
        "end_date": fmt_dt(l["_end_date"]),
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_bay(b):
    return {
        "id": b["id"],
        "bay_code": b["bay_code"],
        "location": b["location"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_work_order(w):
    return {
        "id": w["id"],
        "lease_id": w["lease_id"],
        "service_bay_id": w["service_bay_id"],
        "category": w["category"],
        "description": w["description"],
        "scheduled_start": fmt_dt(w["_scheduled_start"]),
        "scheduled_end": fmt_dt(w["_scheduled_end"]),
        "estimated_cost_cents": w["estimated_cost_cents"],
        "actual_cost_cents": w.get("actual_cost_cents"),
        "odometer_at_service": w.get("odometer_at_service"),
        "completed_at": fmt_dt(w.get("_completed_at")),
        "billed_to": w.get("billed_to"),
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_doc(d):
    return {
        "id": d["id"],
        "owner_operator_id": d["owner_operator_id"],
        "doc_type": d["doc_type"],
        "expires_on": fmt_dt(d["_expires_on"]),
        "status": d["status"],
        "rejection_reason": d.get("rejection_reason"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_quote(q):
    return {
        "id": q["id"],
        "lease_id": q["lease_id"],
        "quote_kind": q["quote_kind"],
        "quoted_price_cents": q["quoted_price_cents"],
        "escrow_credit_cents": q["escrow_credit_cents"],
        "arrears_carried_cents": q["arrears_carried_cents"],
        "amount_due_cents": q["amount_due_cents"],
        "expires_on": fmt_dt(q["_expires_on"]),
        "status": q["status"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }
