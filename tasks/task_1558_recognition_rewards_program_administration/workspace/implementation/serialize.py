"""Entity serializers: internal dicts -> wire format.

Internally, datetime fields are stored as aware datetimes and date fields as
dates; serializers render datetimes as ISO 8601 UTC with three fractional
digits and dates as YYYY-MM-DD. PointLedgerEntry is the sole entity without
updated_at / version (immutable journal record, PRD section 2.4).
"""
from datetime import datetime, date

from db import iso_ms


def _dt(v):
    return iso_ms(v) if isinstance(v, datetime) else v


def _date(v):
    return v.isoformat() if isinstance(v, date) and not isinstance(v, datetime) else v


def _common(e):
    return {
        "id": e["id"],
        "created_at": _dt(e["created_at"]),
        "updated_at": _dt(e["updated_at"]),
        "version": e["version"],
    }


def program(p):
    out = _common(p)
    out.update({
        "name": p["name"],
        "status": p["status"],
        "peer_nomination_enabled": p["peer_nomination_enabled"],
        "manager_nomination_enabled": p["manager_nomination_enabled"],
        "max_points_per_nomination": p["max_points_per_nomination"],
        "point_cost_rate_cents": p["point_cost_rate_cents"],
        "state_rate_map": p["state_rate_map"],
        "grossup_enabled": p["grossup_enabled"],
        "anniversary_milestones": p["anniversary_milestones"],
        "nomination_review_sla_days": p["nomination_review_sla_days"],
        "duplicate_window_days": p["duplicate_window_days"],
        "velocity_limit_per_7_days": p["velocity_limit_per_7_days"],
        "accrual_method": p["accrual_method"],
        "fiscal_year_start_month": p["fiscal_year_start_month"],
    })
    return out


def department(d):
    out = _common(d)
    out.update({
        "name": d["name"],
        "chargeback_account_code": d["chargeback_account_code"],
    })
    return out


def employee(e):
    out = _common(e)
    out.update({
        "employee_ref": e["employee_ref"],
        "full_name": e["full_name"],
        "department_id": e["department_id"],
        "manager_id": e["manager_id"],
        "hire_date": _date(e["hire_date"]),
        "state_code": e["state_code"],
        "program_status": e["program_status"],
        "recognition_tier": e["recognition_tier"],
        "available_points": e["available_points"],
        "held_points": e["held_points"],
        "lifetime_granted_points": e["lifetime_granted_points"],
        "lifetime_redeemed_points": e["lifetime_redeemed_points"],
        "lifetime_expired_points": e["lifetime_expired_points"],
        "ytd_supplemental_wages_cents": e["ytd_supplemental_wages_cents"],
        "ytd_de_minimis_cents": e["ytd_de_minimis_cents"],
    })
    return out


def ledger_entry(e):
    # Immutable journal: id + created_at only, no updated_at/version.
    return {
        "id": e["id"],
        "employee_id": e["employee_id"],
        "entry_type": e["entry_type"],
        "points": e["points"],
        "reference_type": e["reference_type"],
        "reference_id": e["reference_id"],
        "idempotency_key": e["idempotency_key"],
        "note": e["note"],
        "created_at": _dt(e["created_at"]),
    }


def budget(b):
    out = _common(b)
    out.update({
        "program_id": b["program_id"],
        "department_id": b["department_id"],
        "period_start_date": _date(b["period_start_date"]),
        "period_end_date": _date(b["period_end_date"]),
        "allocated_points": b["allocated_points"],
        "reserved_points": b["reserved_points"],
        "committed_points": b["committed_points"],
        "posture": b["posture"],
    })
    return out


def nomination(n):
    out = _common(n)
    out.update({
        "program_id": n["program_id"],
        "nominator_id": n["nominator_id"],
        "nominee_id": n["nominee_id"],
        "type": n["type"],
        "points_requested": n["points_requested"],
        "reason_code": n["reason_code"],
        "message": n["message"],
        "idempotency_key": n["idempotency_key"],
        "status": n["status"],
        "revision_count": n["revision_count"],
        "review_deadline": _dt(n["review_deadline"]),
        "budget_id": n["budget_id"],
        "award_id": n["award_id"],
        "reviewer_id": n["reviewer_id"],
        "decided_at": _dt(n["decided_at"]),
    })
    return out


def award(a):
    out = _common(a)
    out.update({
        "program_id": a["program_id"],
        "employee_id": a["employee_id"],
        "nomination_id": a["nomination_id"],
        "source": a["source"],
        "points": a["points"],
        "points_remaining": a["points_remaining"],
        "status": a["status"],
        "granted_at": _dt(a["granted_at"]),
        "expires_at": _dt(a["expires_at"]),
        "revoked_by_flag_id": a["revoked_by_flag_id"],
    })
    return out


def vendor(v):
    out = _common(v)
    out.update({
        "name": v["name"],
        "vendor_code": v["vendor_code"],
        "daily_ship_capacity": v["daily_ship_capacity"],
        "lead_time_business_days": v["lead_time_business_days"],
        "restocking_fee_percent": v["restocking_fee_percent"],
        "supported_categories": v["supported_categories"],
        "status": v["status"],
    })
    return out


def catalog_item(c):
    out = _common(c)
    out.update({
        "vendor_id": c["vendor_id"],
        "sku": c["sku"],
        "name": c["name"],
        "category": c["category"],
        "point_cost": c["point_cost"],
        "cash_value_cents": c["cash_value_cents"],
        "taxable_class": c["taxable_class"],
        "de_minimis_eligible": c["de_minimis_eligible"],
        "active_window_start": _dt(c["active_window_start"]),
        "active_window_end": _dt(c["active_window_end"]),
        "inventory_quantity": c["inventory_quantity"],
        "status": c["status"],
    })
    return out


def redemption_order(o):
    out = _common(o)
    out.update({
        "employee_id": o["employee_id"],
        "program_id": o["program_id"],
        "catalog_item_id": o["catalog_item_id"],
        "quantity": o["quantity"],
        "points_total": o["points_total"],
        "fulfillment_status": o["fulfillment_status"],
        "escrow_status": o["escrow_status"],
        "ship_date": _date(o["ship_date"]),
        "idempotency_key": o["idempotency_key"],
        "tax_record_id": o["tax_record_id"],
        "restocking_fee_points": o["restocking_fee_points"],
        "delivered_at": _dt(o["delivered_at"]),
    })
    return out


def tax_record(t):
    out = _common(t)
    out.update({
        "employee_id": t["employee_id"],
        "program_id": t["program_id"],
        "redemption_order_id": t["redemption_order_id"],
        "tax_year": t["tax_year"],
        "taxable_value_cents": t["taxable_value_cents"],
        "de_minimis_applied": t["de_minimis_applied"],
        "federal_rate_applied": t["federal_rate_applied"],
        "state_rate_applied": t["state_rate_applied"],
        "estimated_gross_up_cents": t["estimated_gross_up_cents"],
        "final_gross_up_cents": t["final_gross_up_cents"],
        "delta_cents": t["delta_cents"],
        "employer_cost_cents": t["employer_cost_cents"],
        "status": t["status"],
    })
    return out


def accrual_run(r):
    out = _common(r)
    out.update({
        "program_id": r["program_id"],
        "period_year": r["period_year"],
        "period_month": r["period_month"],
        "status": r["status"],
        "accrual_method_used": r["accrual_method_used"],
        "department_breakdown": r["department_breakdown"],
        "total_accrual_cents": r["total_accrual_cents"],
        "total_net_chargeback_cents": r["total_net_chargeback_cents"],
        "variance_cents": r["variance_cents"],
    })
    return out


def abuse_flag(f):
    out = _common(f)
    out.update({
        "employee_id": f["employee_id"],
        "program_id": f["program_id"],
        "rule_code": f["rule_code"],
        "details": f["details"],
        "status": f["status"],
        "raised_by": f["raised_by"],
        "resolved_by": f["resolved_by"],
    })
    return out


def anniversary_event(ev):
    out = _common(ev)
    out.update({
        "program_id": ev["program_id"],
        "employee_id": ev["employee_id"],
        "milestone_years": ev["milestone_years"],
        "scheduled_date": _date(ev["scheduled_date"]),
        "status": ev["status"],
        "award_id": ev["award_id"],
    })
    return out
