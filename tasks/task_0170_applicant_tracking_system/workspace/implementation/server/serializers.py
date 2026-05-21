"""Per-entity dict serialisers. Output is what /GET endpoints return."""
from __future__ import annotations

from typing import Any


def serialize_recruiter(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "email": r["email"],
        "full_name": r["full_name"],
        "department_code": r["department_code"],
        "is_active": r["is_active"],
    }


def serialize_hiring_manager(h: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": h["id"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
        "email": h["email"],
        "full_name": h["full_name"],
        "department_code": h["department_code"],
        "budget_cents": h["budget_cents"],
    }


def serialize_interviewer(i: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "email": i["email"],
        "full_name": i["full_name"],
        "department_code": i["department_code"],
        "is_certified_for_eeo": i["is_certified_for_eeo"],
    }


def serialize_candidate(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "email": c["email"],
        "full_name": c["full_name"],
        "source": c["source"],
        "referrer_employee_id": c.get("referrer_employee_id"),
        "is_in_eeo_protected_class": c.get("is_in_eeo_protected_class", False),
    }


def serialize_eeo_record(e: dict[str, Any]) -> dict[str, Any]:
    # EEORecord deliberately has no version/updated_at.
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "candidate_id": e["candidate_id"],
        "gender": e["gender"],
        "ethnicity": e["ethnicity"],
        "veteran_status": e["veteran_status"],
        "disability_status": e["disability_status"],
        "submitted_at": e["submitted_at"],
    }


def serialize_requisition(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "recruiter_id": r["recruiter_id"],
        "hiring_manager_id": r["hiring_manager_id"],
        "job_title": r["job_title"],
        "department_code": r["department_code"],
        "seniority_level": r["seniority_level"],
        "headcount": r["headcount"],
        "filled_count": r.get("filled_count", 0),
        "active_offer_count": r.get("active_offer_count", 0),
        "posted_at": r.get("posted_at"),
        "closed_at": r.get("closed_at"),
        "budget_cents": r["budget_cents"],
        "target_diversity_goal_id": r.get("target_diversity_goal_id"),
        "status": r["status"],
    }


def serialize_application(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "requisition_id": a["requisition_id"],
        "candidate_id": a["candidate_id"],
        "stage": a["stage"],
        "rejection_reason": a.get("rejection_reason"),
        "panel_average_score": a.get("panel_average_score"),
        "pinned_eeo_snapshot_version": a.get("pinned_eeo_snapshot_version"),
    }


def serialize_interview(i: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "application_id": i["application_id"],
        "interviewer_id": i["interviewer_id"],
        "scheduled_start_at": i["scheduled_start_at"],
        "scheduled_end_at": i["scheduled_end_at"],
        "status": i["status"],
    }


def serialize_interview_feedback(f: dict[str, Any]) -> dict[str, Any]:
    # InterviewFeedback has only id + created_at; submitted_at is the immutable stamp.
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "interview_id": f["interview_id"],
        "interviewer_id": f["interviewer_id"],
        "overall_score": f["overall_score"],
        "recommendation": f["recommendation"],
        "submitted_at": f["submitted_at"],
    }


def serialize_offer(o: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "application_id": o["application_id"],
        "requisition_id": o["requisition_id"],
        "base_salary_cents": o["base_salary_cents"],
        "sign_on_bonus_cents": o["sign_on_bonus_cents"],
        "annual_equity_cents": o["annual_equity_cents"],
        "total_first_year_comp_cents": o["total_first_year_comp_cents"],
        "pinned_requisition_version": o.get("pinned_requisition_version"),
        "status": o["status"],
        "expires_at": o.get("expires_at"),
        "negotiation_round": o.get("negotiation_round", 0),
    }


def serialize_approval_step(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "offer_id": s["offer_id"],
        "step_order": s["step_order"],
        "approver_role": s["approver_role"],
        "required_approver_id": s["required_approver_id"],
        "decision": s["decision"],
        "decided_at": s.get("decided_at"),
    }


def serialize_background_check(b: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "offer_id": b["offer_id"],
        "vendor": b["vendor"],
        "status": b["status"],
        "ordered_at": b["ordered_at"],
        "result_received_at": b.get("result_received_at"),
    }


def serialize_referral_bonus(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "candidate_id": r["candidate_id"],
        "referrer_employee_id": r.get("referrer_employee_id"),
        "requisition_id": r["requisition_id"],
        "base_amount_cents": r.get("base_amount_cents", 0),
        "diversity_uplift_cents": r.get("diversity_uplift_cents", 0),
        "total_amount_cents": r.get("total_amount_cents", 0),
        "status": r["status"],
        "payable_at": r.get("payable_at"),
    }


def serialize_diversity_goal(g: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": g["id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
        "department_code": g["department_code"],
        "period_year": g["period_year"],
        "target_protected_class_percentage": g["target_protected_class_percentage"],
        "realized_percentage": g.get("realized_percentage", 0.00),
        "projected_percentage": g.get("projected_percentage", 0.00),
        "locked": g.get("locked", False),
        "locked_at": g.get("locked_at"),
    }
