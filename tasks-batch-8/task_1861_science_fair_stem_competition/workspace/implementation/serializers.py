"""Serialize internal entity dicts to API output dicts.

Common fields: id, created_at, updated_at, version — except for
JudgeConflict and ScoreSheet which carry only id and created_at.
"""

from decimal import Decimal


def _decimal_to_number(d):
    """Render a Decimal at its natural scale as a float for JSON output.

    normalized_score is 3dp; aggregates are 2dp. We keep them as Decimal
    internally and emit floats so jsonify renders e.g. 0.5 / 81.25.
    """
    if d is None:
        return None
    return float(d)


def fair_edition_out(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "status": e["status"],
        "normalization_algorithm": e["normalization_algorithm"],
        "max_judges_per_project": e["max_judges_per_project"],
        "min_quorum_ratio_pct": e["min_quorum_ratio_pct"],
        "advancement_freeze": e["advancement_freeze"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def category_out(c):
    return {
        "id": c["id"],
        "fair_edition_id": c["fair_edition_id"],
        "code": c["code"],
        "name": c["name"],
        "grade_band": c["grade_band"],
        "advancement_slots": c["advancement_slots"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def mentor_out(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "recognition_points": m["recognition_points"],
        "leaderboard_points": m["leaderboard_points"],
        "recognition_tier": m["recognition_tier"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def project_out(p):
    return {
        "id": p["id"],
        "fair_edition_id": p["fair_edition_id"],
        "category_id": p["category_id"],
        "mentor_id": p["mentor_id"],
        "title": p["title"],
        "team_size": p["team_size"],
        "involves_human_subjects": p["involves_human_subjects"],
        "involves_animal_subjects": p["involves_animal_subjects"],
        "registration_status": p["registration_status"],
        "ethics_status": p["ethics_status"],
        "inspection_status": p["inspection_status"],
        "judging_status": p["judging_status"],
        "provisional_aggregate": _decimal_to_number(p["provisional_aggregate"]),
        "final_aggregate": _decimal_to_number(p["final_aggregate"]),
        "advancement_result": p["advancement_result"],
        "advancement_rank": p["advancement_rank"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def research_plan_out(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "plan_text": r["plan_text"],
        "risk_level": r["risk_level"],
        "status": r["status"],
        "review_cycle_count": r["review_cycle_count"],
        "approved_plan_version": r["approved_plan_version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ethics_review_out(r):
    return {
        "id": r["id"],
        "research_plan_id": r["research_plan_id"],
        "reviewer_mentor_id": r["reviewer_mentor_id"],
        "decision": r["decision"],
        "rationale": r["rationale"],
        "decided_at": r["decided_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def judge_out(j):
    return {
        "id": j["id"],
        "fair_edition_id": j["fair_edition_id"],
        "full_name": j["full_name"],
        "expertise_category_ids": list(j["expertise_category_ids"]),
        "max_assignments": j["max_assignments"],
        "active_assignment_count": j["active_assignment_count"],
        "status": j["status"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def judge_conflict_out(c):
    # JudgeConflict carries only id and created_at among standard fields
    return {
        "id": c["id"],
        "judge_id": c["judge_id"],
        "project_id": c["project_id"],
        "reason": c["reason"],
        "created_at": c["created_at"],
    }


def judging_assignment_out(a):
    return {
        "id": a["id"],
        "project_id": a["project_id"],
        "judge_id": a["judge_id"],
        "status": a["status"],
        "assigned_at": a["assigned_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def score_sheet_out(s):
    # ScoreSheet carries only id and created_at among standard fields
    return {
        "id": s["id"],
        "judging_assignment_id": s["judging_assignment_id"],
        "project_id": s["project_id"],
        "judge_id": s["judge_id"],
        "raw_score": s["raw_score"],
        "normalized_score": _decimal_to_number(s["normalized_score"]),
        "submitted_at": s["submitted_at"],
        "created_at": s["created_at"],
    }


def booth_assignment_out(b):
    return {
        "id": b["id"],
        "project_id": b["project_id"],
        "hall": b["hall"],
        "booth_number": b["booth_number"],
        "inspection_window_start": b["inspection_window_start"],
        "inspection_window_end": b["inspection_window_end"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def award_out(a):
    return {
        "id": a["id"],
        "fair_edition_id": a["fair_edition_id"],
        "project_id": a["project_id"],
        "award_type": a["award_type"],
        "scholarship_amount_cents": a["scholarship_amount_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def scholarship_pool_out(p):
    return {
        "id": p["id"],
        "fair_edition_id": p["fair_edition_id"],
        "total_cents": p["total_cents"],
        "remaining_cents": p["remaining_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
