"""Entity minting, serializers (live-computed fields), cascade helpers.

Version discipline (PRD 2.4 / global_invariants.version_bump_scope): an entity's
`version` increments by exactly 1 only on direct writes — its own create/action/
transition endpoints, including system-driven transitions whose from/to live on
that entity. Pure recomputation of derived fields never increments version.
"""
import uuid

from db import db
from timeutil import fmt_ts
from services import calc


def mint():
    """Fresh system-managed common fields."""
    now = db.now()
    return {
        "id": str(uuid.uuid4()),
        "_created": now,
        "_updated": now,
        "_seq": db.next_seq(),
        "version": 1,
    }


def touch(entity):
    entity["_updated"] = db.now()


def bump(entity):
    entity["version"] += 1
    touch(entity)


def created_at(e):
    return fmt_ts(e["_created"])


def updated_at(e):
    return fmt_ts(e["_updated"])


# ---------------------------------------------------------------------------
# Recompute propagation: derived fields are computed live in the serializers;
# here we refresh stored forward-looking sponsorship estimates and audit stamps.
# ---------------------------------------------------------------------------

def refresh_event(ev):
    """Called after any mutation that can change event-derived values:
    headcounts/hours-driven sponsorship provisionals and the event audit stamp."""
    for sp in db.sponsorships.values():
        if sp["event_id"] == ev["id"] and sp["status"] in ("PLEDGED", "COMMITTED"):
            new_val = calc.provisional_amount(sp)
            if new_val != sp["provisional_amount_cents"]:
                sp["provisional_amount_cents"] = new_val
                touch(sp)
    touch(ev)


def maybe_demote_project(project):
    """LOCKED -> MATCHED automatic demotion when supervision/headcount invariant breaks."""
    if project["status"] != "LOCKED":
        return
    confirmed = calc.project_confirmed_count(project)
    required = calc.supervision_requirement(project)
    active = calc.active_staff_leads(project)
    if confirmed < project["min_volunteers"] or required > active:
        project["status"] = "MATCHED"
        bump(project)


def after_project_mutation(project):
    maybe_demote_project(project)
    touch(project)
    if project["event_id"]:
        ev = db.events.get(project["event_id"])
        if ev is not None:
            refresh_event(ev)


def cancel_registration_effects(reg):
    """Shared compensating effects when a registration becomes CANCELLED."""
    if reg["transport_manifest_id"] is not None:
        reg["transport_manifest_id"] = None
    project = db.projects.get(reg["project_id"])
    if project is not None:
        after_project_mutation(project)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_partner(p):
    score, survey_count = calc.partner_reputation(p)
    return {
        "id": p["id"],
        "name": p["name"],
        "contact_email": p["contact_email"],
        "status": p["status"],
        "reputation_score": score,
        "survey_count": survey_count,
        "completed_event_count": calc.partner_completed_event_count(p),
        "created_at": created_at(p),
        "updated_at": updated_at(p),
        "version": p["version"],
    }


def ser_event(ev):
    registered, confirmed, checked_in = calc.headcounts(ev)
    projected, committed = calc.event_spend(ev)
    credit, net = calc.sponsorship_credit_and_net(ev)
    return {
        "id": ev["id"],
        "name": ev["name"],
        "event_start_at": ev["event_start_at"],
        "event_end_at": ev["event_end_at"],
        "status": ev["status"],
        "readiness_posture": calc.event_posture(ev),
        "budget_cents": ev["budget_cents"],
        "waiver_document_version": ev["waiver_document_version"],
        "projected_spend_cents": projected,
        "committed_spend_cents": committed,
        "available_budget_cents": ev["budget_cents"] - projected,
        "sponsorship_credit_cents": credit,
        "net_event_cost_cents": net,
        "registered_headcount": registered,
        "confirmed_headcount": confirmed,
        "checked_in_headcount": checked_in,
        "total_scheduled_hours": calc.event_total_scheduled_hours(ev),
        "total_verified_hours": calc.event_total_verified_hours(ev),
        "source_event_id": ev["source_event_id"],
        "repeat_booking_bonus": ev["repeat_booking_bonus"],
        "avg_feedback_rating": calc.event_avg_feedback(ev),
        "created_at": created_at(ev),
        "updated_at": updated_at(ev),
        "version": ev["version"],
    }


def ser_project(p):
    return {
        "id": p["id"],
        "nonprofit_id": p["nonprofit_id"],
        "event_id": p["event_id"],
        "title": p["title"],
        "required_skills": list(p["required_skills"]),
        "min_volunteers": p["min_volunteers"],
        "max_volunteers": p["max_volunteers"],
        "status": p["status"],
        "confirmed_volunteer_count": calc.project_confirmed_count(p),
        "required_staff_leads": calc.supervision_requirement(p),
        "active_staff_leads": calc.active_staff_leads(p),
        "site_prep_complete": calc.site_prep_complete(p),
        "created_at": created_at(p),
        "updated_at": updated_at(p),
        "version": p["version"],
    }


def ser_volunteer(v):
    return {
        "id": v["id"],
        "full_name": v["full_name"],
        "email": v["email"],
        "department": v["department"],
        "date_of_birth": v["date_of_birth"],
        "skills": list(v["skills"]),
        "dietary_tags": list(v["dietary_tags"]),
        "is_staff_lead": v["is_staff_lead"],
        "created_at": created_at(v),
        "updated_at": updated_at(v),
        "version": v["version"],
    }


def ser_registration(r):
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "project_id": r["project_id"],
        "volunteer_id": r["volunteer_id"],
        "rsvp_status": r["rsvp_status"],
        "waiver_status": r["waiver_status"],
        "waiver_signed_version": r["waiver_signed_version"],
        "waiver_signer_relation": r["waiver_signer_relation"],
        "waiver_signer_name": r["waiver_signer_name"],
        "media_consent": r["media_consent"],
        "is_minor": calc.reg_is_minor(r),
        "wants_transport": r["wants_transport"],
        "wants_meal": r["wants_meal"],
        "transport_manifest_id": r["transport_manifest_id"],
        "scheduled_hours_credit": r["scheduled_hours_credit"],
        "verified_hours_credit": calc.registration_verified_hours(r),
        "checked_in_at": r["checked_in_at"],
        "created_at": created_at(r),
        "updated_at": updated_at(r),
        "version": r["version"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "event_id": o["event_id"],
        "project_id": o["project_id"],
        "lines": o["lines"],
        "order_total_cents": o["order_total_cents"],
        "status": o["status"],
        "created_by_user_id": o["created_by_user_id"],
        "rejection_reason": o["rejection_reason"],
        "created_at": created_at(o),
        "updated_at": updated_at(o),
        "version": o["version"],
    }


def ser_vehicle(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "seat_capacity": v["seat_capacity"],
        "created_at": created_at(v),
        "updated_at": updated_at(v),
        "version": v["version"],
    }


def ser_manifest(m):
    return {
        "id": m["id"],
        "event_id": m["event_id"],
        "vehicle_id": m["vehicle_id"],
        "depart_at": m["depart_at"],
        "return_at": m["return_at"],
        "cost_cents": m["cost_cents"],
        "status": m["status"],
        "assigned_seats": calc.manifest_assigned_seats(m),
        "created_at": created_at(m),
        "updated_at": updated_at(m),
        "version": m["version"],
    }


def ser_meal_plan(m):
    return {
        "id": m["id"],
        "event_id": m["event_id"],
        "vendor_name": m["vendor_name"],
        "per_person_cost_cents": m["per_person_cost_cents"],
        "dietary_surcharge_cents": m["dietary_surcharge_cents"],
        "status": m["status"],
        "ordered_headcount": m["ordered_headcount"],
        "dietary_headcount": m["dietary_headcount"],
        "total_cost_cents": m["total_cost_cents"],
        "created_at": created_at(m),
        "updated_at": updated_at(m),
        "version": m["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "project_id": a["project_id"],
        "event_id": a["event_id"],
        "lead_volunteer_id": a["lead_volunteer_id"],
        "status": a["status"],
        "created_at": created_at(a),
        "updated_at": updated_at(a),
        "version": a["version"],
    }


def ser_sponsorship(sp):
    return {
        "id": sp["id"],
        "event_id": sp["event_id"],
        "sponsor_name": sp["sponsor_name"],
        "match_type": sp["match_type"],
        "rate_cents": sp["rate_cents"],
        "pledge_cap_cents": sp["pledge_cap_cents"],
        "status": sp["status"],
        "effective_cap_cents": calc.effective_cap_cents(sp),
        "provisional_amount_cents": sp["provisional_amount_cents"],
        "settled_amount_cents": sp["settled_amount_cents"],
        "created_at": created_at(sp),
        "updated_at": updated_at(sp),
        "version": sp["version"],
    }


def ser_impact(rec):
    return {
        "id": rec["id"],
        "registration_id": rec["registration_id"],
        "project_id": rec["project_id"],
        "event_id": rec["event_id"],
        "hours_attended": rec["hours_attended"],
        "photo_count": rec["photo_count"],
        "story_text": rec["story_text"],
        "status": rec["status"],
        "rejection_reason": rec["rejection_reason"],
        "created_at": created_at(rec),
        "updated_at": updated_at(rec),
        "version": rec["version"],
    }


def ser_survey(s):
    # FeedbackSurvey carries only id + created_at (immutable; no updated_at/version).
    return {
        "id": s["id"],
        "registration_id": s["registration_id"],
        "rating": s["rating"],
        "would_repeat": s["would_repeat"],
        "comments": s["comments"],
        "created_at": created_at(s),
    }


def sort_entities(items):
    """created_at ASC; creation sequence breaks ties (deterministic, never id-based)."""
    return sorted(items, key=lambda e: (e["_created"], e["_seq"]))
