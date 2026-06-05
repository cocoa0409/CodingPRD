"""Entity -> output-dict projections.

Computed fields (PRD: derived on read) are recomputed here so reads always
reflect the current logical clock and current graph state. Stored records keep
their persisted scalar fields; computed fields are layered on at serialization.
"""
from services import compute


def caseworker(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "role_type": r["role_type"],
        "email": r["email"],
        "active": r["active"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def referral(r):
    return {
        "id": r["id"],
        "status": r["status"],
        "reporter_type": r["reporter_type"],
        "child_name": r["child_name"],
        "alleged_maltreatment": r["alleged_maltreatment"],
        "priority_factors": r.get("priority_factors") or [],
        "response_priority": r.get("response_priority"),
        "screening_score": r.get("screening_score"),
        "screened_in_by": r.get("screened_in_by"),
        "linked_case_id": r.get("linked_case_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def investigation(r):
    return {
        "id": r["id"],
        "referral_id": r["referral_id"],
        "investigator_id": r["investigator_id"],
        "status": r["status"],
        "safety_factors": r.get("safety_factors") or [],
        "protective_capacity": r.get("protective_capacity"),
        "safety_decision_score": r.get("safety_decision_score"),
        "removal_recommended": r.get("removal_recommended"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def case(r):
    months, breached = compute.permanency_clock(r)
    return {
        "id": r["id"],
        "investigation_id": r["investigation_id"],
        "status": r["status"],
        "removal_date": r.get("removal_date"),
        "permanency_goal": r["permanency_goal"],
        "months_in_care": months,
        "tpr_clock_breached": breached,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def child(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "full_name": r["full_name"],
        "date_of_birth": r["date_of_birth"],
        "status": r["status"],
        "current_placement_id": r.get("current_placement_id"),
        "age_years": compute.age_years(r),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def foster_home(r):
    return {
        "id": r["id"],
        "licensing_worker_id": r["licensing_worker_id"],
        "home_name": r["home_name"],
        "bed_capacity": r["bed_capacity"],
        "license_status": r["license_status"],
        "license_expires_at": r.get("license_expires_at"),
        "max_age_years": r["max_age_years"],
        "accepts_maltreatment": r.get("accepts_maltreatment") or [],
        "active_placement_count": compute.active_placement_count(r["id"]),
        "clearances_complete": compute.clearances_complete(r["id"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def caregiver_screening(r):
    return {
        "id": r["id"],
        "foster_home_id": r["foster_home_id"],
        "member_name": r["member_name"],
        "status": r["status"],
        "disqualifying": r["disqualifying"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def placement(r):
    return {
        "id": r["id"],
        "child_id": r["child_id"],
        "foster_home_id": r["foster_home_id"],
        "case_id": r["case_id"],
        "status": r["status"],
        "start_at": r.get("start_at"),
        "end_at": r.get("end_at"),
        "match_score": r.get("match_score"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def case_plan(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "status": r["status"],
        "required_visits_per_month": r["required_visits_per_month"],
        "objectives_total": r["objectives_total"],
        "objectives_met": r["objectives_met"],
        "compliance_pct": r["compliance_pct"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def visitation(r):
    return {
        "id": r["id"],
        "case_plan_id": r["case_plan_id"],
        "child_id": r["child_id"],
        "status": r["status"],
        "supervision": r["supervision"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def hearing(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "hearing_type": r["hearing_type"],
        "status": r["status"],
        "scheduled_at": r["scheduled_at"],
        "ruling": r.get("ruling"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
