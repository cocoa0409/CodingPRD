"""Serializers — produce the JSON-safe entity dicts returned by the API.

The internal store carries some bookkeeping keys (e.g. `first_active_at`,
`suspended_at`) that are not part of the public response shape. Each
serializer below picks out the documented fields explicitly so downstream
clients see exactly what the SCAFFOLD/PRD specifies.
"""

from services.computations import (
    compute_triennial_status,
    compute_requires_transition_plan,
)
from core.store import DISTRICTS


def district_dto(d: dict) -> dict:
    return {
        "id": d["id"],
        "name": d.get("name"),
        "state_code": d.get("state_code"),
        "current_date": d.get("current_date"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
        "version": d.get("version"),
    }


def student_dto(s: dict, *, recompute_lazy: bool = True) -> dict:
    """Return the Student DTO with triennial_status/requires_transition_plan recomputed lazily."""
    out = {
        "id": s["id"],
        "district_id": s.get("district_id"),
        "external_student_number": s.get("external_student_number"),
        "date_of_birth": s.get("date_of_birth"),
        "parent_user_id": s.get("parent_user_id"),
        "current_iep_id": s.get("current_iep_id"),
        "current_eligibility_evaluation_id": s.get("current_eligibility_evaluation_id"),
        "triennial_reevaluation_due_date": s.get("triennial_reevaluation_due_date"),
        "triennial_status": s.get("triennial_status", "NOT_APPLICABLE"),
        "requires_transition_plan": s.get("requires_transition_plan", False),
        "lre_classification": s.get("lre_classification", "NOT_APPLICABLE"),
        "created_at": s.get("created_at"),
        "updated_at": s.get("updated_at"),
        "version": s.get("version"),
    }
    if recompute_lazy:
        district = DISTRICTS.get(s.get("district_id"))
        if district is not None:
            current_date = district.get("current_date")
            if current_date:
                out["triennial_status"] = compute_triennial_status(s, current_date)
                out["requires_transition_plan"] = compute_requires_transition_plan(s, current_date)
    return out


def evaluation_dto(e: dict) -> dict:
    return {
        "id": e["id"],
        "student_id": e.get("student_id"),
        "district_id": e.get("district_id"),
        "evaluation_type": e.get("evaluation_type"),
        "is_reevaluation": e.get("is_reevaluation", False),
        "disability_categories": e.get("disability_categories", []),
        "evaluator_user_id": e.get("evaluator_user_id"),
        "requested_at": e.get("requested_at"),
        "consent_received_at": e.get("consent_received_at"),
        "finalized_at": e.get("finalized_at"),
        "status": e.get("status"),
        "created_at": e.get("created_at"),
        "updated_at": e.get("updated_at"),
        "version": e.get("version"),
    }


def consent_dto(c: dict) -> dict:
    return {
        "id": c["id"],
        "student_id": c.get("student_id"),
        "district_id": c.get("district_id"),
        "scope": c.get("scope"),
        "target_resource_type": c.get("target_resource_type"),
        "target_resource_id": c.get("target_resource_id"),
        "parent_user_id": c.get("parent_user_id"),
        "requested_at": c.get("requested_at"),
        "decided_at": c.get("decided_at"),
        "withdrawn_at": c.get("withdrawn_at"),
        "status": c.get("status"),
        "created_at": c.get("created_at"),
    }


def iep_dto(i: dict) -> dict:
    return {
        "id": i["id"],
        "student_id": i.get("student_id"),
        "district_id": i.get("district_id"),
        "meeting_held_at": i.get("meeting_held_at"),
        "effective_start_date": i.get("effective_start_date"),
        "scheduled_review_date": i.get("scheduled_review_date"),
        "total_instructional_minutes_per_week": i.get("total_instructional_minutes_per_week"),
        "total_school_day_minutes_per_week": i.get("total_school_day_minutes_per_week"),
        "special_education_minutes_per_week": i.get("special_education_minutes_per_week", 0),
        "lre_percentage_instructional": i.get("lre_percentage_instructional", 0.00),
        "lre_percentage_school_day": i.get("lre_percentage_school_day", 0.00),
        "requires_transition_plan": i.get("requires_transition_plan", False),
        "transition_plan_id": i.get("transition_plan_id"),
        "status": i.get("status"),
        "created_at": i.get("created_at"),
        "updated_at": i.get("updated_at"),
        "version": i.get("version"),
    }


def goal_dto(g: dict) -> dict:
    return {
        "id": g["id"],
        "iep_id": g.get("iep_id"),
        "student_id": g.get("student_id"),
        "district_id": g.get("district_id"),
        "domain": g.get("domain"),
        "description": g.get("description"),
        "objectives": g.get("objectives", []),
        "mastery_score": g.get("mastery_score", 0.00),
        "mastery_tier": g.get("mastery_tier", "INSUFFICIENT_PROGRESS"),
        "status": g.get("status"),
        "created_at": g.get("created_at"),
        "updated_at": g.get("updated_at"),
        "version": g.get("version"),
    }


def progress_report_dto(r: dict) -> dict:
    return {
        "id": r["id"],
        "iep_goal_id": r.get("iep_goal_id"),
        "iep_id": r.get("iep_id"),
        "student_id": r.get("student_id"),
        "reporting_period_index": r.get("reporting_period_index"),
        "reported_by_user_id": r.get("reported_by_user_id"),
        "objective_progress": r.get("objective_progress", []),
        "narrative": r.get("narrative"),
        "created_at": r.get("created_at"),
    }


def service_dto(s: dict) -> dict:
    return {
        "id": s["id"],
        "iep_id": s.get("iep_id"),
        "student_id": s.get("student_id"),
        "district_id": s.get("district_id"),
        "service_type": s.get("service_type"),
        "minutes_per_week": s.get("minutes_per_week"),
        "provider_user_id": s.get("provider_user_id"),
        "location_setting": s.get("location_setting"),
        "consent_id": s.get("consent_id"),
        "total_prescribed_minutes_to_date": s.get("total_prescribed_minutes_to_date", 0),
        "total_delivered_minutes": s.get("total_delivered_minutes", 0),
        "total_cancelled_minutes": s.get("total_cancelled_minutes", 0),
        "compensatory_minutes_owed": s.get("compensatory_minutes_owed", 0),
        "utilization_percent": s.get("utilization_percent", 0.00),
        "status": s.get("status"),
        "created_at": s.get("created_at"),
        "updated_at": s.get("updated_at"),
        "version": s.get("version"),
    }


def session_dto(s: dict) -> dict:
    return {
        "id": s["id"],
        "related_service_id": s.get("related_service_id"),
        "iep_id": s.get("iep_id"),
        "student_id": s.get("student_id"),
        "scheduled_start": s.get("scheduled_start"),
        "scheduled_end": s.get("scheduled_end"),
        "scheduled_minutes": s.get("scheduled_minutes"),
        "actual_minutes": s.get("actual_minutes"),
        "status": s.get("status"),
        "created_at": s.get("created_at"),
        "updated_at": s.get("updated_at"),
        "version": s.get("version"),
    }


def transition_plan_dto(t: dict) -> dict:
    return {
        "id": t["id"],
        "iep_id": t.get("iep_id"),
        "student_id": t.get("student_id"),
        "post_secondary_goal": t.get("post_secondary_goal"),
        "required_courses": t.get("required_courses", []),
        "outside_agency_referrals": t.get("outside_agency_referrals", []),
        "parent_invitation_documented": t.get("parent_invitation_documented", False),
        "student_invitation_documented": t.get("student_invitation_documented", False),
        "status": t.get("status"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "version": t.get("version"),
    }
