"""Public representations of each entity."""
from core import fmt_dt, bgcheck_status, bond_status, schedule_status


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def client_out(c):
    d = _base(c)
    d.update({
        "name": c["name"],
        "timezone": c["timezone"],
        "home_zip": c["home_zip"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "mileage_rate_cents_per_mile": c["mileage_rate_cents_per_mile"],
        "ot_threshold_hours": c["ot_threshold_hours"],
        "ot_multiplier": c["ot_multiplier"],
        "min_visit_minutes": c["min_visit_minutes"],
        "status": c["status"],
        "outstanding_balance_cents": c["outstanding_balance_cents"],
    })
    return d


def family_contact_out(fc):
    d = _base(fc)
    d.update({
        "client_id": fc["client_id"],
        "name": fc["name"],
        "email": fc["email"],
        "relationship": fc["relationship"],
    })
    return d


def caregiver_out(cg):
    d = _base(cg)
    d.update({
        "name": cg["name"],
        "home_zip": cg["home_zip"],
        "hourly_pay_cents": cg["hourly_pay_cents"],
        "status": cg["status"],
        "committed_minutes": cg["committed_minutes"],
    })
    return d


def background_check_out(bc):
    d = _base(bc)
    d.update({
        "caregiver_id": bc["caregiver_id"],
        "status": bgcheck_status(bc),
        "decided_at": fmt_dt(bc.get("decided_at")),
        "expires_at": fmt_dt(bc.get("expires_at")),
    })
    return d


def bond_out(b):
    d = _base(b)
    d.update({
        "caregiver_id": b["caregiver_id"],
        "coverage_cents": b["coverage_cents"],
        "effective_date": fmt_dt(b["effective_date"]),
        "expiry_date": fmt_dt(b["expiry_date"]),
        "status": bond_status(b),
    })
    return d


def schedule_out(s):
    d = _base(s)
    d.update({
        "client_id": s["client_id"],
        "task_type": s["task_type"],
        "frequency": s["frequency"],
        "day_of_week": s["day_of_week"],
        "start_time": s["start_time"],
        "duration_minutes": s["duration_minutes"],
        "start_date": fmt_dt(s["start_date"]),
        "end_date": fmt_dt(s["end_date"]),
        "status": schedule_status(s),
    })
    return d


def visit_out(v):
    d = _base(v)
    d.update({
        "client_id": v["client_id"],
        "schedule_id": v["schedule_id"],
        "caregiver_id": v["caregiver_id"],
        "task_type": v["task_type"],
        "scheduled_start": fmt_dt(v["scheduled_start"]),
        "scheduled_end": fmt_dt(v["scheduled_end"]),
        "actual_start": fmt_dt(v.get("actual_start")),
        "actual_end": fmt_dt(v.get("actual_end")),
        "mileage_miles": v["mileage_miles"],
        "status": v["status"],
        "hourly_rate_cents": v["hourly_rate_cents"],
        "mileage_rate_cents_per_mile": v["mileage_rate_cents_per_mile"],
        "ot_threshold_hours": v["ot_threshold_hours"],
        "ot_multiplier": v["ot_multiplier"],
        "min_visit_minutes": v["min_visit_minutes"],
        "estimated_cost_cents": v.get("estimated_cost_cents"),
    })
    return d


def assignment_out(a):
    d = _base(a)
    d.update({
        "visit_id": a["visit_id"],
        "caregiver_id": a["caregiver_id"],
        "status": a["status"],
    })
    return d


def addon_out(a):
    d = _base(a)
    d.update({
        "visit_id": a["visit_id"],
        "addon_type": a["addon_type"],
        "fee_cents": a["fee_cents"],
        "status": a["status"],
    })
    return d


def invoice_out(inv):
    d = _base(inv)
    d.update({
        "client_id": inv["client_id"],
        "visit_id": inv["visit_id"],
        "status": inv["status"],
        "labor_cents": inv["labor_cents"],
        "mileage_cents": inv["mileage_cents"],
        "addon_cents": inv["addon_cents"],
        "total_cents": inv["total_cents"],
    })
    return d


def ltc_policy_out(p):
    d = _base(p)
    d.update({
        "client_id": p["client_id"],
        "payer_name": p["payer_name"],
        "benefit_type": p["benefit_type"],
        "daily_benefit_cents": p["daily_benefit_cents"],
        "reimbursement_rate": p["reimbursement_rate"],
        "daily_cap_cents": p["daily_cap_cents"],
        "lifetime_max_cents": p["lifetime_max_cents"],
        "reimbursed_to_date_cents": p["reimbursed_to_date_cents"],
        "status": p["status"],
    })
    return d


def claim_out(cl):
    d = _base(cl)
    d.update({
        "invoice_id": cl["invoice_id"],
        "ltc_policy_id": cl["ltc_policy_id"],
        "benefit_type": cl["benefit_type"],
        "status": cl["status"],
        "eligible_cents": cl["eligible_cents"],
        "reimbursed_cents": cl["reimbursed_cents"],
        "client_responsibility_cents": cl["client_responsibility_cents"],
    })
    return d


def wellness_out(w):
    d = _base(w)
    d.update({
        "visit_id": w["visit_id"],
        "client_id": w["client_id"],
        "severity": w["severity"],
        "reason": w["reason"],
        "status": w["status"],
        "acknowledged_by": w.get("acknowledged_by"),
    })
    return d


def visit_log_out(l):
    return {
        "id": l["id"],
        "created_at": fmt_dt(l["created_at"]),
        "visit_id": l["visit_id"],
        "entry_type": l["entry_type"],
        "note": l["note"],
    }
