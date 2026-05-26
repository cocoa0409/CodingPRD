"""Serialisers map internal dicts to API response shapes."""
from __future__ import annotations

import db
from services.department import compute_committed_offer_cents
from services.diversity import compute_pool_pct, compute_hire_pct


def ser_department(d: dict) -> dict:
    return {
        "id": d["id"],
        "name": d["name"],
        "cost_center_code": d["cost_center_code"],
        "hiring_budget_cents": d["hiring_budget_cents"],
        "committed_offer_cents": compute_committed_offer_cents(d["id"]),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def _req_filled_count(req_id: str) -> int:
    return sum(
        1 for a in db.applications.values()
        if a["requisition_id"] == req_id and a["status"] == "HIRED"
    )


def ser_requisition(r: dict) -> dict:
    return {
        "id": r["id"],
        "department_id": r["department_id"],
        "title": r["title"],
        "target_level": r["target_level"],
        "base_salary_min_cents": r["base_salary_min_cents"],
        "base_salary_max_cents": r["base_salary_max_cents"],
        "status": r["status"],
        "submitter_user_id": r.get("submitter_user_id"),
        "approver_user_id": r.get("approver_user_id"),
        "approved_at": r.get("approved_at"),
        "openings": r["openings"],
        "filled_count": _req_filled_count(r["id"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_candidate(c: dict) -> dict:
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "source_channel": c["source_channel"],
        "referrer_user_id": c.get("referrer_user_id"),
        "eeo_ethnicity": c["eeo_ethnicity"],
        "eeo_gender": c["eeo_gender"],
        "eeo_veteran": c["eeo_veteran"],
        "eeo_disability": c["eeo_disability"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_application(a: dict) -> dict:
    return {
        "id": a["id"],
        "candidate_id": a["candidate_id"],
        "requisition_id": a["requisition_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_interview(i: dict) -> dict:
    return {
        "id": i["id"],
        "application_id": i["application_id"],
        "round_number": i["round_number"],
        "scheduled_at": i["scheduled_at"],
        "duration_minutes": i["duration_minutes"],
        "panel_user_ids": list(i["panel_user_ids"]),
        "status": i["status"],
        "aggregate_score": i.get("aggregate_score"),
        "recommendation": i.get("recommendation"),
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_interview_feedback(f: dict) -> dict:
    return {
        "id": f["id"],
        "interview_id": f["interview_id"],
        "panelist_user_id": f["panelist_user_id"],
        "score": f["score"],
        "comments": f["comments"],
        "created_at": f["created_at"],
    }


def ser_offer(o: dict) -> dict:
    return {
        "id": o["id"],
        "application_id": o["application_id"],
        "base_salary_cents": o["base_salary_cents"],
        "signing_bonus_cents": o["signing_bonus_cents"],
        "status": o["status"],
        "comp_approver_user_id": o.get("comp_approver_user_id"),
        "vp_approver_user_id": o.get("vp_approver_user_id"),
        "submitter_user_id": o.get("submitter_user_id"),
        "extended_at": o.get("extended_at"),
        "expires_at": o.get("expires_at"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_background_check(b: dict) -> dict:
    return {
        "id": b["id"],
        "offer_id": b["offer_id"],
        "candidate_id": b["candidate_id"],
        "status": b["status"],
        "vendor_reference": b["vendor_reference"],
        "completed_at": b.get("completed_at"),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_referral_bonus(r: dict) -> dict:
    return {
        "id": r["id"],
        "candidate_id": r["candidate_id"],
        "referrer_user_id": r["referrer_user_id"],
        "offer_id": r["offer_id"],
        "estimated_amount_cents": r["estimated_amount_cents"],
        "payable_amount_cents": r.get("payable_amount_cents"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_diversity_goal(g: dict) -> dict:
    return {
        "id": g["id"],
        "department_id": g["department_id"],
        "target_level": g["target_level"],
        "period_year": g["period_year"],
        "target_underrepresented_pct": g["target_underrepresented_pct"],
        "pool_underrepresented_pct": compute_pool_pct(g),
        "hire_underrepresented_pct": compute_hire_pct(g),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }
