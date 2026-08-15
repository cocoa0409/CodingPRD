"""Serializers: exact public field sets per entity (PRD 2.5 + entity tables).
Computed fields are derived at read time against the logical clock."""

from db import store
from util import iso
import services as svc


def employee_view(e):
    tenure = svc.tenure_days(e)
    score = svc.risk_score(e["id"])
    provisional, committed = svc.annual_accumulators(e["id"])
    return {
        "id": e["id"],
        "employee_number": e["employee_number"],
        "full_name": e["full_name"],
        "email": e["email"],
        "department": e["department"],
        "job_level": e["job_level"],
        "is_recruiter": e["is_recruiter"],
        "hire_date": iso(e["hire_date"]),
        "employment_status": e["employment_status"],
        "terminated_at": iso(e["terminated_at"]),
        "tenure_days": tenure,
        "fraud_strikes": e["fraud_strikes"],
        "risk_score": score,
        "referral_suspended": score >= svc.SUSPEND_THRESHOLD,
        "annual_provisional_cents": provisional,
        "annual_committed_cents": committed,
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def candidate_view(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "normalized_email": c["normalized_email"],
        "phone": c["phone"],
        "prior_application_at": iso(c["prior_application_at"]),
        "global_status": c["global_status"],
        "last_terminal_outcome_at": iso(c["last_terminal_outcome_at"]),
        "cooldown_until": iso(svc.candidate_cooldown_until(c)),
        "hired_via_referral_id": c["hired_via_referral_id"],
        "departed_at": iso(c["departed_at"]),
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def requisition_view(r):
    return {
        "id": r["id"],
        "req_number": r["req_number"],
        "title": r["title"],
        "department": r["department"],
        "level": r["level"],
        "referral_eligible": r["referral_eligible"],
        "hard_to_fill": r["hard_to_fill"],
        "openings": r["openings"],
        "filled_count": r["filled_count"],
        "status": r["status"],
        "opened_at": iso(r["opened_at"]),
        "filled_by_candidate_id": r["filled_by_candidate_id"],
        "open_referral_count": svc.open_referral_count(r),
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def policy_view(p):
    return {
        "id": p["id"],
        "effective_from": iso(p["effective_from"]),
        "effective_to": iso(p["effective_to"]),
        "min_tenure_days": p["min_tenure_days"],
        "duplicate_cooldown_months": p["duplicate_cooldown_months"],
        "referral_expiry_days": p["referral_expiry_days"],
        "hire_pct": p["hire_pct"],
        "retention_days": p["retention_days"],
        "clawback_days": p["clawback_days"],
        "annual_cap_cents": p["annual_cap_cents"],
        "velocity_limit": p["velocity_limit"],
        "tier_ic_cents": p["tier_ic_cents"],
        "tier_senior_cents": p["tier_senior_cents"],
        "tier_manager_cents": p["tier_manager_cents"],
        "tier_director_cents": p["tier_director_cents"],
        "tier_executive_cents": p["tier_executive_cents"],
        "status": p["status"],
        "note": p["note"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def campaign_view(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "job_requisition_id": c["job_requisition_id"],
        "multiplier_bps": c["multiplier_bps"],
        "flat_addon_cents": c["flat_addon_cents"],
        "window_start": iso(c["window_start"]),
        "window_end": iso(c["window_end"]),
        "budget_cents": c["budget_cents"],
        "max_payouts": c["max_payouts"],
        "reserved_cents": c["reserved_cents"],
        "spent_cents": c["spent_cents"],
        "remaining_cents": svc.campaign_remaining(c),
        "payouts_count": svc.campaign_payouts_count(c),
        "status": c["status"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def referral_view(r):
    return {
        "id": r["id"],
        "referrer_id": r["referrer_id"],
        "candidate_id": r["candidate_id"],
        "job_requisition_id": r["job_requisition_id"],
        "campaign_id": r["campaign_id"],
        "policy_version_id": r["policy_version_id"],
        "status": r["status"],
        "submitted_at": iso(r["submitted_at"]),
        "note": r["note"],
        "bonus_base_cents": r["bonus_base_cents"],
        "campaign_uplift_cents": r["campaign_uplift_cents"],
        "bonus_total_cents": r["bonus_total_cents"],
        "hire_date": iso(r["hire_date"]),
        "retention_due_at": iso(r["retention_due_at"]),
        "clawback_until": iso(r["clawback_until"]),
        "last_decision_reason": r["last_decision_reason"],
        "uplift_spent_cents": r["uplift_spent_cents"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def milestone_view(m):
    return {
        "id": m["id"],
        "referral_id": m["referral_id"],
        "kind": m["kind"],
        "amount_cents": m["amount_cents"],
        "withholding_cents": m["withholding_cents"],
        "net_cents": m["net_cents"],
        "status": m["status"],
        "earned_at": iso(m["earned_at"]),
        "payroll_batch_id": m["payroll_batch_id"],
        "recovery_status": m["recovery_status"],
        "approved_by_user_id": m["approved_by_user_id"],
        "created_at": iso(m["created_at"]),
        "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def batch_view(b):
    totals = svc.batch_totals(b)
    return {
        "id": b["id"],
        "period_label": b["period_label"],
        "status": b["status"],
        "total_gross_cents": totals["total_gross_cents"],
        "total_withholding_cents": totals["total_withholding_cents"],
        "total_net_cents": totals["total_net_cents"],
        "milestone_count": totals["milestone_count"],
        "created_at": iso(b["created_at"]),
        "updated_at": iso(b["updated_at"]),
        "version": b["version"],
    }


def abuse_case_view(c):
    return {
        "id": c["id"],
        "employee_id": c["employee_id"],
        "referral_id": c["referral_id"],
        "case_type": c["case_type"],
        "risk_weight": c["risk_weight"],
        "status": c["status"],
        "raised_by_user_id": c["raised_by_user_id"],
        "decided_by_user_id": c["decided_by_user_id"],
        "confirmed_at": iso(c["confirmed_at"]),
        "resolution_note": c["resolution_note"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def tax_profile_view(t):
    return {
        "id": t["id"],
        "employee_id": t["employee_id"],
        "filing_status": t["filing_status"],
        "withholding_method": t["withholding_method"],
        "supplemental_rate_bps": t["supplemental_rate_bps"],
        "ytd_carryover_cents": t["ytd_carryover_cents"],
        "ytd_paid_gross_cents": svc.ytd_paid_gross(t["employee_id"]),
        "status": t["status"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def event_view(e):
    return {
        "id": e["id"],
        "referral_id": e["referral_id"],
        "event_type": e["event_type"],
        "from_state": e["from_state"],
        "to_state": e["to_state"],
        "actor_user_id": e["actor_user_id"],
        "note": e["note"],
        "created_at": iso(e["created_at"]),
    }
