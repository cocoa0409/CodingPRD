"""Entity serializers — computed fields are derived at read time so every
response reflects the live store."""

from services import calc


def grant_view(g):
    prov_cents, prov_pct = calc.provisional_carryover(g)
    return {
        "id": g["id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
        "fiscal_year": g["fiscal_year"],
        "total_allocation_cents": g["total_allocation_cents"],
        "carryover_in_cents": g["carryover_in_cents"],
        "admin_reserve_cents": g["admin_reserve_cents"],
        "poverty_measure": g["poverty_measure"],
        "equitable_count_method": g["equitable_count_method"],
        "status": g["status"],
        "carryover_waiver_status": g["carryover_waiver_status"],
        "carryover_waiver_justification": g["carryover_waiver_justification"],
        "carryover_waiver_decided_at": g["carryover_waiver_decided_at"],
        "net_allocable_cents": g["net_allocable_cents"],
        "ranking_version": g["ranking_version"],
        "liquidated_cents": g["liquidated_cents"],
        "pending_cents": g["pending_cents"],
        "provisional_carryover_cents": prov_cents,
        "provisional_carryover_pct_bp": prov_pct,
        "final_carryover_cents": g["final_carryover_cents"],
        "final_carryover_pct_bp": g["final_carryover_pct_bp"],
        "monitoring_clearance": g["monitoring_clearance"],
    }


def school_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "name": s["name"],
        "nces_id": s["nces_id"],
        "grade_span_low": s["grade_span_low"],
        "grade_span_high": s["grade_span_high"],
        "is_active": s["is_active"],
    }


def private_school_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "nonprofit_verified": p["nonprofit_verified"],
        "low_income_resident_count": p["low_income_resident_count"],
        "contact_email": p["contact_email"],
    }


def snapshot_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "grant_id": s["grant_id"],
        "measure": s["measure"],
        "entries": s["entries"],
        "status": s["status"],
        "certified_at": s["certified_at"],
    }


def allocation_view(a):
    served = a["eligibility_flag"] != "BELOW_THRESHOLD" or a["serve_elected"]
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "grant_id": a["grant_id"],
        "school_id": a["school_id"],
        "snapshot_id": a["snapshot_id"],
        "low_income_student_count": a["low_income_student_count"],
        "total_student_count": a["total_student_count"],
        "poverty_pct_bp": a["poverty_pct_bp"],
        "rank_position": a["rank_position"],
        "eligibility_flag": a["eligibility_flag"],
        "program_model": a["program_model"],
        "serve_elected": a["serve_elected"],
        "served": served,
        "per_pupil_cents": a["per_pupil_cents"],
        "allocation_amount_cents": a["allocation_amount_cents"],
        "liquidated_cents": a["liquidated_cents"],
        "pending_cents": a["pending_cents"],
        "supplement_ok": a["supplement_ok"],
        "status": a["status"],
    }


def set_aside_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "grant_id": s["grant_id"],
        "category": s["category"],
        "minimum_cents": s["minimum_cents"],
        "reserved_cents": s["reserved_cents"],
        "school_distributed_minimum_cents": s["school_distributed_minimum_cents"],
        "liquidated_cents": s["liquidated_cents"],
    }


def sns_view(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "school_allocation_id": d["school_allocation_id"],
        "methodology": d["methodology"],
        "coverage_start_date": d["coverage_start_date"],
        "coverage_end_date": d["coverage_end_date"],
        "narrative": d["narrative"],
        "status": d["status"],
        "submitted_by_user_id": d["submitted_by_user_id"],
        "reviewed_by_user_id": d["reviewed_by_user_id"],
        "review_note": d["review_note"],
        "attempt_count": d["attempt_count"],
    }


def consultation_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "grant_id": c["grant_id"],
        "private_school_id": c["private_school_id"],
        "status": c["status"],
        "sessions": c["sessions"],
        "sessions_count": len(c["sessions"]),
        "agreed_low_income_count": c["agreed_low_income_count"],
        "affirmation_signed_at": c["affirmation_signed_at"],
        "affirmation_signer_id": c["affirmation_signer_id"],
        "dispute_reason": c["dispute_reason"],
        "complaint_determination": c["complaint_determination"],
    }


def expenditure_view(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "grant_id": e["grant_id"],
        "school_allocation_id": e["school_allocation_id"],
        "set_aside_id": e["set_aside_id"],
        "amount_cents": e["amount_cents"],
        "function_code": e["function_code"],
        "description": e["description"],
        "incurred_date": e["incurred_date"],
        "supplant_screen": e["supplant_screen"],
        "status": e["status"],
        "submitted_by_user_id": e["submitted_by_user_id"],
        "reviewed_by_user_id": e["reviewed_by_user_id"],
        "review_note": e["review_note"],
        "disallow_reason": e["disallow_reason"],
        "reclassified_to_fund_source": e["reclassified_to_fund_source"],
    }


def amendment_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "grant_id": a["grant_id"],
        "lines": a["lines"],
        "prior_amounts": a["prior_amounts"],
        "status": a["status"],
        "submitted_by_user_id": a["submitted_by_user_id"],
        "decided_by_user_id": a["decided_by_user_id"],
        "decision_note": a["decision_note"],
    }


def visit_view(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "grant_id": v["grant_id"],
        "visit_start_date": v["visit_start_date"],
        "visit_end_date": v["visit_end_date"],
        "scope": v["scope"],
        "lead_monitor_id": v["lead_monitor_id"],
        "status": v["status"],
        "report_issued_at": v["report_issued_at"],
    }


def finding_view(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "visit_id": f["visit_id"],
        "citation": f["citation"],
        "severity": f["severity"],
        "description": f["description"],
        "cap_due_date": f["cap_due_date"],
        "status": f["status"],
        "cap_narrative": f["cap_narrative"],
        "cap_attempt_count": f["cap_attempt_count"],
        "cap_submitted_by_user_id": f["cap_submitted_by_user_id"],
        "decided_by_user_id": f["decided_by_user_id"],
        "return_note": f["return_note"],
    }
