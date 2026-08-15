"""Domain helpers: entity lookups, serializers, cascades, auto-flip rule."""

from datetime import datetime, timezone

from db import db
from errors import err_not_found, err_forbidden
from utils import format_iso, now_utc, touch


# ---------- lookups ----------

def get_season(sid):
    s = db.seasons.get(sid)
    if s is None:
        raise err_not_found(f"Season {sid} not found")
    return s


def get_school_target(sid):
    s = db.school_targets.get(sid)
    if s is None:
        raise err_not_found(f"SchoolTarget {sid} not found")
    return s


def get_campus_event(eid):
    e = db.campus_events.get(eid)
    if e is None:
        raise err_not_found(f"CampusEvent {eid} not found")
    return e


def get_candidate(cid):
    c = db.candidates.get(cid)
    if c is None:
        raise err_not_found(f"Candidate {cid} not found")
    return c


def get_application(aid):
    a = db.applications.get(aid)
    if a is None:
        raise err_not_found(f"Application {aid} not found")
    return a


def get_employee(eid):
    e = db.employees.get(eid)
    if e is None:
        raise err_not_found(f"Employee {eid} not found")
    return e


def get_interview_day(did):
    d = db.interview_days.get(did)
    if d is None:
        raise err_not_found(f"InterviewDay {did} not found")
    return d


def get_interview_slot(sid):
    s = db.interview_slots.get(sid)
    if s is None:
        raise err_not_found(f"InterviewSlot {sid} not found")
    return s


def get_evaluation(eid):
    e = db.evaluations.get(eid)
    if e is None:
        raise err_not_found(f"Evaluation {eid} not found")
    return e


def get_offer(oid):
    o = db.offers.get(oid)
    if o is None:
        raise err_not_found(f"Offer {oid} not found")
    return o


def get_stipend_disbursement(sid):
    s = db.stipend_disbursements.get(sid)
    if s is None:
        raise err_not_found(f"StipendDisbursement {sid} not found")
    return s


def get_intern_project(pid):
    p = db.intern_projects.get(pid)
    if p is None:
        raise err_not_found(f"InternProject {pid} not found")
    return p


def get_project_assignment(aid):
    a = db.project_assignments.get(aid)
    if a is None:
        raise err_not_found(f"ProjectAssignment {aid} not found")
    return a


def get_intern_evaluation(eid):
    e = db.intern_evaluations.get(eid)
    if e is None:
        raise err_not_found(f"InternEvaluation {eid} not found")
    return e


# ---------- serializers ----------

def season_view(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "status": s["status"],
        "application_open_at": format_iso(s["_application_open_at"]),
        "application_close_at": format_iso(s["_application_close_at"]),
        "interview_window_start_at": format_iso(s["_interview_window_start_at"]),
        "interview_window_end_at": format_iso(s["_interview_window_end_at"]),
        "offer_window_open_at": format_iso(s["_offer_window_open_at"]),
        "offer_window_close_at": format_iso(s["_offer_window_close_at"]),
        "exploding_offer_hours_default": s["exploding_offer_hours_default"],
        "deadline_policy_mode": s["deadline_policy_mode"],
        "max_extension_hours": s["max_extension_hours"],
        "shortlist_score_threshold": s["shortlist_score_threshold"],
        "stipend_budget_cents": s["stipend_budget_cents"],
        "stipend_reserved_cents": s["stipend_reserved_cents"],
        "stipend_disbursed_cents": s["stipend_disbursed_cents"],
        "applications_total_count": s["applications_total_count"],
        "offers_extended_count": s["offers_extended_count"],
        "offers_accepted_count": s["offers_accepted_count"],
        "completed_assignments_count": s["completed_assignments_count"],
        "return_offers_extended_count": s["return_offers_extended_count"],
        "return_offers_accepted_count": s["return_offers_accepted_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def school_target_view(t):
    return {
        "id": t["id"],
        "season_id": t["season_id"],
        "school_name": t["school_name"],
        "tier": t["tier"],
        "application_cap": t["application_cap"],
        "stipend_region": t["stipend_region"],
        "exploding_offer_hours_override": t.get("exploding_offer_hours_override"),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def campus_event_view(e):
    return {
        "id": e["id"],
        "season_id": e["season_id"],
        "school_target_id": e["school_target_id"],
        "event_type": e["event_type"],
        "start_at": format_iso(e["_start_at"]),
        "end_at": format_iso(e["_end_at"]),
        "status": e["status"],
        "resume_count": e["resume_count"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def candidate_view(c):
    return {
        "id": c["id"],
        "email": c["email"],
        "full_name": c["full_name"],
        "expected_graduation_date": format_iso(c["_expected_graduation_date"]),
        "is_alumnus": c["is_alumnus"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def application_view(a):
    return {
        "id": a["id"],
        "season_id": a["season_id"],
        "candidate_id": a["candidate_id"],
        "school_target_id": a["school_target_id"],
        "status": a["status"],
        "referral_flag": a["referral_flag"],
        "prior_internship_count": a["prior_internship_count"],
        "relocation_distance_miles": a["relocation_distance_miles"],
        "screening_score_provisional": a["screening_score_provisional"],
        "screening_score_final": a["screening_score_final"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def employee_view(e):
    return {
        "id": e["id"],
        "season_id": e["season_id"],
        "full_name": e["full_name"],
        "email": e["email"],
        "alma_mater_school_name": e.get("alma_mater_school_name"),
        "daily_slot_limit": e["daily_slot_limit"],
        "max_interns": e["max_interns"],
        "can_evaluate": e["can_evaluate"],
        "can_mentor": e["can_mentor"],
        "calibrated": e["calibrated"],
        "assigned_intern_count": e["assigned_intern_count"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def interview_day_view(d):
    return {
        "id": d["id"],
        "season_id": d["season_id"],
        "window_start_at": format_iso(d["_window_start_at"]),
        "window_end_at": format_iso(d["_window_end_at"]),
        "capacity": d["capacity"],
        "booked_count": d["booked_count"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def interview_slot_view(s):
    return {
        "id": s["id"],
        "interview_day_id": s["interview_day_id"],
        "application_id": s["application_id"],
        "evaluator_id": s["evaluator_id"],
        "start_at": format_iso(s["_start_at"]),
        "end_at": format_iso(s["_end_at"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def evaluation_view(e):
    return {
        "id": e["id"],
        "interview_slot_id": e["interview_slot_id"],
        "evaluator_id": e["evaluator_id"],
        "score": e["score"],
        "recommendation": e["recommendation"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def offer_view(o):
    return {
        "id": o["id"],
        "application_id": o["application_id"],
        "status": o["status"],
        "weekly_rate_cents": o["weekly_rate_cents"],
        "duration_weeks": o["duration_weeks"],
        "sign_on_bonus_cents": o["sign_on_bonus_cents"],
        "total_comp_cents": o["total_comp_cents"],
        "policy_hours_snapshot": o.get("policy_hours_snapshot"),
        "extended_at": format_iso(o["_extended_at"]) if o.get("_extended_at") else None,
        "deadline_at": format_iso(o["_deadline_at"]) if o.get("_deadline_at") else None,
        "extension_hours_granted": o["extension_hours_granted"],
        "stipend_amount_cents": o.get("stipend_amount_cents"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def stipend_disbursement_view(d):
    return {
        "id": d["id"],
        "offer_id": d["offer_id"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def intern_project_view(p):
    return {
        "id": p["id"],
        "season_id": p["season_id"],
        "title": p["title"],
        "capacity": p["capacity"],
        "assigned_count": p["assigned_count"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def project_assignment_view(a):
    return {
        "id": a["id"],
        "application_id": a["application_id"],
        "intern_project_id": a["intern_project_id"],
        "mentor_id": a["mentor_id"],
        "status": a["status"],
        "return_offer_decision": a["return_offer_decision"],
        "return_offer_outcome": a["return_offer_outcome"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def intern_evaluation_view(e):
    return {
        "id": e["id"],
        "project_assignment_id": e["project_assignment_id"],
        "eval_type": e["eval_type"],
        "rating": e["rating"],
        "would_rehire": e["would_rehire"],
        "submitted_by_mentor_id": e["submitted_by_mentor_id"],
        "created_at": e["created_at"],
    }


# ---------- cross-entity helpers ----------

def application_season(application):
    return get_season(application["season_id"])


def offer_season(offer):
    return get_season(get_application(offer["application_id"])["season_id"])


def offer_application(offer):
    return get_application(offer["application_id"])


def disbursement_season(d):
    offer = get_offer(d["offer_id"])
    return offer_season(offer)


def assignment_season(a):
    app = get_application(a["application_id"])
    return get_season(app["season_id"])


def maybe_lazy_expire_offer(offer):
    """Lazy flip: any offer operation observing now > deadline_at flips EXTENDED->EXPIRED."""
    if offer["status"] != "EXTENDED":
        return False
    if offer.get("_deadline_at") is None:
        return False
    now = now_utc()
    if now > offer["_deadline_at"]:
        offer["status"] = "EXPIRED"
        touch(offer)
        # conditional application cascade
        app = get_application(offer["application_id"])
        if app["status"] == "OFFER_PENDING":
            app["status"] = "EXPIRED"
            touch(app)
        return True
    return False


def auto_flip_application(application, suppress=False):
    """Re-evaluate the auto-flip rule for the application after slot mutations.

    When app is INTERVIEW_SCHEDULED and every slot is terminal:
      - 0 COMPLETED slots -> SHORTLISTED
      - >=1 COMPLETED slots -> DECISION_PENDING
    """
    if suppress:
        return
    if application["status"] != "INTERVIEW_SCHEDULED":
        return
    slots = [s for s in db.interview_slots.values() if s["application_id"] == application["id"]]
    if not slots:
        return
    if not all(s["status"] in ("COMPLETED", "CANCELLED", "NO_SHOW") for s in slots):
        return
    completed = sum(1 for s in slots if s["status"] == "COMPLETED")
    if completed >= 1:
        application["status"] = "DECISION_PENDING"
    else:
        application["status"] = "SHORTLISTED"
    touch(application)


def check_candidate_owns(resource_candidate_id):
    from flask import g
    if g.user_id != resource_candidate_id:
        raise err_forbidden("Candidate may only act on own resources")
