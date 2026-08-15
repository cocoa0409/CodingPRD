"""Per-entity serializers: exactly the scaffold-declared fields, datetimes ISO."""
from util import fmt_dt
from services import receivable_live


def sponsor(s):
    return {
        "id": s["id"], "name": s["name"], "sponsor_type": s["sponsor_type"],
        "payment_method": s["payment_method"],
        "salary_cap_annual_cents": s.get("salary_cap_annual_cents"),
        "f_and_a_rate_bps": s["f_and_a_rate_bps"],
        "late_payment_apr_bps": s.get("late_payment_apr_bps", 0),
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def person(p):
    return {
        "id": p["id"], "full_name": p["full_name"], "role_type": p["role_type"],
        "institutional_base_salary_annual_cents": p["institutional_base_salary_annual_cents"],
        "appointment_months": p["appointment_months"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def award(a):
    return {
        "id": a["id"], "sponsor_id": a["sponsor_id"], "pi_id": a["pi_id"],
        "award_number": a["award_number"], "title": a["title"],
        "project_start_date": fmt_dt(a["project_start_date"]),
        "original_end_date": fmt_dt(a["original_end_date"]),
        "current_end_date": fmt_dt(a["current_end_date"]),
        "total_obligated_cents": a["total_obligated_cents"],
        "salary_cap_annual_cents": a.get("salary_cap_annual_cents"),
        "f_and_a_rate_bps": a["f_and_a_rate_bps"],
        "payment_method": a["payment_method"],
        "fringe_rate_bps": a["fringe_rate_bps"],
        "cost_share_committed_cents": a.get("cost_share_committed_cents", 0),
        "status": a["status"], "posture": a["posture"],
        "mtdc_spent_cents": a["mtdc_spent_cents"],
        "f_and_a_accrued_cents": a["f_and_a_accrued_cents"],
        "total_direct_spent_cents": a["total_direct_spent_cents"],
        "cost_share_met_cents": a["cost_share_met_cents"],
        "cumulative_drawn_cents": a["cumulative_drawn_cents"],
        "reserved_draw_cents": a["reserved_draw_cents"],
        "available_draw_pool_cents": a["available_draw_pool_cents"],
        "nce_count": a["nce_count"],
        "residual_deobligated_cents": a.get("residual_deobligated_cents"),
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def budget_line(l):
    return {
        "id": l["id"], "award_id": l["award_id"], "category": l["category"],
        "authorized_cents": l["authorized_cents"],
        "baseline_authorized_cents": l["baseline_authorized_cents"],
        "spent_cents": l["spent_cents"],
        "mtdc_eligible_cents": l.get("mtdc_eligible_cents", 0),
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


def commitment(c):
    # EffortCommitment is immutable: id and created_at only (no updated_at/version).
    return {
        "id": c["id"], "award_id": c["award_id"], "person_id": c["person_id"],
        "committed_effort_pct": c["committed_effort_pct"],
        "is_key_personnel": c.get("is_key_personnel", False),
        "created_at": c["created_at"],
    }


def expenditure(e):
    return {
        "id": e["id"], "award_id": e["award_id"], "budget_line_id": e["budget_line_id"],
        "person_id": e.get("person_id"),
        "transferred_from_id": e.get("transferred_from_id"),
        "expenditure_type": e["expenditure_type"],
        "amount_cents": e.get("amount_cents"),
        "fringe_cents": e.get("fringe_cents", 0),
        "over_cap_cents": e.get("over_cap_cents", 0),
        "mtdc_eligible_cents": e.get("mtdc_eligible_cents", 0),
        "effort_pct": e.get("effort_pct"),
        "period_months": e.get("period_months"),
        "transaction_date": fmt_dt(e["transaction_date"]),
        "is_cost_share": e.get("is_cost_share", False),
        "cash_disbursed": e.get("cash_disbursed", False),
        "is_allocable": e.get("is_allocable"),
        "is_reasonable": e.get("is_reasonable"),
        "is_consistent": e.get("is_consistent"),
        "description": e.get("description"),
        "status": e["status"],
        "disallow_reason": e.get("disallow_reason"),
        "posted_at": fmt_dt(e.get("posted_at")),
        "invoiced_receivable_id": e.get("invoiced_receivable_id"),
        "submitted_by_user_id": e.get("submitted_by_user_id"),
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


def cost_transfer(t):
    return {
        "id": t["id"], "source_expenditure_id": t["source_expenditure_id"],
        "target_award_id": t["target_award_id"],
        "target_budget_line_id": t["target_budget_line_id"],
        "justification": t["justification"],
        "enhanced_justification": t.get("enhanced_justification"),
        "is_retroactive": t.get("is_retroactive"),
        "days_since_posting": t.get("days_since_posting"),
        "status": t["status"],
        "created_by_user_id": t.get("created_by_user_id"),
        "submitted_by_user_id": t.get("submitted_by_user_id"),
        "approved_by_user_id": t.get("approved_by_user_id"),
        "countersigned_by_user_id": t.get("countersigned_by_user_id"),
        "deny_reason": t.get("deny_reason"),
        "created_at": t["created_at"], "updated_at": t["updated_at"], "version": t["version"],
    }


def cycle(c):
    return {
        "id": c["id"], "cycle_code": c["cycle_code"],
        "period_start": fmt_dt(c["period_start"]), "period_end": fmt_dt(c["period_end"]),
        "cycle_months": c["cycle_months"],
        "actual_fringe_rate_bps": c.get("actual_fringe_rate_bps"),
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def statement(s):
    return {
        "id": s["id"], "cycle_id": s["cycle_id"], "person_id": s["person_id"],
        "award_id": s.get("award_id"),
        "statement_kind": s["statement_kind"],
        "committed_effort_pct": s["committed_effort_pct"],
        "charged_effort_pct": s["charged_effort_pct"],
        "certified_effort_pct": s.get("certified_effort_pct"),
        "variance_pp": s.get("variance_pp"),
        "payroll_adjustment_note": s.get("payroll_adjustment_note"),
        "key_reduction_flag": s.get("key_reduction_flag", False),
        "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def subaward(s):
    return {
        "id": s["id"], "award_id": s["award_id"],
        "subrecipient_name": s["subrecipient_name"],
        "total_subaward_cents": s["total_subaward_cents"],
        "risk_rating": s["risk_rating"],
        "start_date": fmt_dt(s["start_date"]), "end_date": fmt_dt(s["end_date"]),
        "status": s["status"],
        "invoiced_to_date_cents": s.get("invoiced_to_date_cents", 0),
        "mtdc_consumed_cents": s.get("mtdc_consumed_cents", 0),
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def invoice(i):
    return {
        "id": i["id"], "subaward_id": i["subaward_id"],
        "invoice_number": i["invoice_number"],
        "period_start": fmt_dt(i["period_start"]), "period_end": fmt_dt(i["period_end"]),
        "current_period_direct_cents": i["current_period_direct_cents"],
        "current_period_f_and_a_cents": i["current_period_f_and_a_cents"],
        "cumulative_direct_cents": i["cumulative_direct_cents"],
        "mtdc_portion_cents": i["mtdc_portion_cents"],
        "audit_reference": i.get("audit_reference"),
        "return_reason": i.get("return_reason"),
        "status": i["status"],
        "prime_expenditure_id": i.get("prime_expenditure_id"),
        "created_at": i["created_at"], "updated_at": i["updated_at"], "version": i["version"],
    }


def report(r):
    return {
        "id": r["id"], "award_id": r["award_id"], "report_type": r["report_type"],
        "due_date": fmt_dt(r["due_date"]), "status": r["status"],
        "submitted_at": fmt_dt(r.get("submitted_at")),
        "days_overdue": r.get("days_overdue", 0),
        "reject_reason": r.get("reject_reason"),
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def drawdown(d):
    return {
        "id": d["id"], "award_id": d["award_id"], "amount_cents": d["amount_cents"],
        "status": d["status"],
        "eligible_pool_at_submission": d.get("eligible_pool_at_submission"),
        "reject_reason": d.get("reject_reason"),
        "submitted_at": fmt_dt(d.get("submitted_at")),
        "settled_at": fmt_dt(d.get("settled_at")),
        "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
    }


def receivable(r):
    days_out, bucket, accrued, outstanding = receivable_live(r)
    return {
        "id": r["id"], "award_id": r["award_id"],
        "period_start": fmt_dt(r["period_start"]), "period_end": fmt_dt(r["period_end"]),
        "amount_cents": r["amount_cents"],
        "invoice_date": fmt_dt(r["invoice_date"]),
        "days_outstanding": days_out, "aging_bucket": bucket,
        "accrued_interest_cents": accrued,
        "disputed_at": fmt_dt(r.get("disputed_at")),
        "total_disputed_days": r.get("total_disputed_days", 0),
        "interest_paid_cents": r.get("interest_paid_cents", 0),
        "principal_paid_cents": r.get("principal_paid_cents", 0),
        "outstanding_total_cents": outstanding,
        "status": r["status"],
        "dispute_reason": r.get("dispute_reason"),
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def modification(m):
    return {
        "id": m["id"], "award_id": m["award_id"], "mod_type": m["mod_type"],
        "extension_months": m.get("extension_months"),
        "rebudget_lines": m.get("rebudget_lines"),
        "justification": m["justification"],
        "requires_sponsor": m.get("requires_sponsor"),
        "status": m["status"],
        "sponsor_decision_reason": m.get("sponsor_decision_reason"),
        "created_at": m["created_at"], "updated_at": m["updated_at"], "version": m["version"],
    }


def ffr(f):
    return {
        "id": f["id"], "award_id": f["award_id"], "status": f["status"],
        "unliquidated_obligations_cents": f.get("unliquidated_obligations_cents"),
        "total_expenditures_cents": f.get("total_expenditures_cents"),
        "cost_share_shortfall_cents": f.get("cost_share_shortfall_cents", 0),
        "residual_cents": f.get("residual_cents"),
        "return_reason": f.get("return_reason"),
        "created_at": f["created_at"], "updated_at": f["updated_at"], "version": f["version"],
    }
