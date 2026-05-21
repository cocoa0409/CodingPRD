"""Entity-to-JSON serializers."""

from typing import Any, Dict


def _common(entity: Dict[str, Any], include_version: bool = True) -> Dict[str, Any]:
    out = {
        "id": entity["id"],
        "created_at": entity["created_at"],
    }
    if "updated_at" in entity:
        out["updated_at"] = entity["updated_at"]
    if include_version and "version" in entity:
        out["version"] = entity["version"]
    return out


def employee_view(e: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common(e),
        "full_name": e["full_name"],
        "email": e["email"],
        "department": e["department"],
        "job_level": e["job_level"],
        "manager_employee_id": e.get("manager_employee_id"),
        "base_salary_cents": e["base_salary_cents"],
        "equity_units_outstanding": e.get("equity_units_outstanding", 0),
        "status": e["status"],
        "hire_date": e["hire_date"],
    }


def cycle_view(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common(c),
        "name": c["name"],
        "cadence": c["cadence"],
        "status": c["status"],
        "review_window_start": c["review_window_start"],
        "review_window_end": c["review_window_end"],
        "bell_curve_target": c["bell_curve_target"],
        "merit_budget_cents": c["merit_budget_cents"],
        "equity_refresh_pool_units": c["equity_refresh_pool_units"],
        "merit_budget_consumed_cents": c.get("merit_budget_consumed_cents", 0),
        "equity_pool_consumed_units": c.get("equity_pool_consumed_units", 0),
    }


def review_case_view(rc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common(rc),
        "cycle_id": rc["cycle_id"],
        "subject_employee_id": rc["subject_employee_id"],
        "manager_employee_id": rc.get("manager_employee_id"),
        "status": rc["status"],
        "manager_rating": rc.get("manager_rating"),
        "final_rating": rc.get("final_rating"),
        "weighted_goal_score": rc.get("weighted_goal_score", 0),
        "peer_feedback_count": rc.get("peer_feedback_count", 0),
        "revision_count": rc.get("revision_count", 0),
    }


def goal_view(g: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common(g),
        "review_case_id": g["review_case_id"],
        "title": g["title"],
        "weight": g["weight"],
        "self_score": g.get("self_score"),
        "manager_score": g.get("manager_score"),
    }


def feedback_view(fr: Dict[str, Any]) -> Dict[str, Any]:
    # FeedbackRequest is append-only: only id and created_at; no updated_at/version
    return {
        "id": fr["id"],
        "created_at": fr["created_at"],
        "review_case_id": fr["review_case_id"],
        "reviewer_employee_id": fr["reviewer_employee_id"],
        "relation": fr["relation"],
        "status": fr["status"],
        "narrative": fr.get("narrative"),
        "submitted_at": fr.get("submitted_at"),
    }


def calibration_session_view(cs: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common(cs),
        "cycle_id": cs["cycle_id"],
        "department": cs["department"],
        "facilitator_employee_id": cs["facilitator_employee_id"],
        "status": cs["status"],
        "proposed_ratings": cs.get("proposed_ratings", []),
        "bell_curve_distribution": cs.get("bell_curve_distribution", {}),
        "committed_at": cs.get("committed_at"),
    }


def pip_case_view(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common(p),
        "cycle_id": p["cycle_id"],
        "subject_employee_id": p["subject_employee_id"],
        "triggering_review_case_id": p["triggering_review_case_id"],
        "duration_days": p["duration_days"],
        "starts_at": p["starts_at"],
        "ends_at": p["ends_at"],
        "status": p["status"],
    }


def comp_plan_view(cp: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common(cp),
        "cycle_id": cp["cycle_id"],
        "subject_employee_id": cp["subject_employee_id"],
        "pinned_review_case_id": cp.get("pinned_review_case_id"),
        "pinned_review_case_version": cp.get("pinned_review_case_version"),
        "pinned_base_salary_cents": cp.get("pinned_base_salary_cents"),
        "merit_increase_cents": cp.get("merit_increase_cents", 0),
        "promotion_to_level": cp.get("promotion_to_level"),
        "equity_refresh_units": cp.get("equity_refresh_units", 0),
        "status": cp["status"],
        "approved_at": cp.get("approved_at"),
    }


def audit_event_view(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "actor_role": a["actor_role"],
        "actor_user_id": a["actor_user_id"],
        "entity_type": a["entity_type"],
        "entity_id": a["entity_id"],
        "action": a["action"],
        "payload_hash": a["payload_hash"],
        "occurred_at": a["occurred_at"],
    }
