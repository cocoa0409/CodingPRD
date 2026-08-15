"""Entity serializers — exactly the scaffold-declared fields plus the four
common fields (id, created_at, updated_at, version)."""
import calc
from timeutil import fmt_dt


def _base(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def program(g):
    d = _base(g)
    d.update({
        "name": g["name"],
        "total_capacity": g["total_capacity"],
        "max_reserve_slots": g["max_reserve_slots"],
        "no_answer_threshold": g["no_answer_threshold"],
        "escalation_retry_hours": g["escalation_retry_hours"],
        "contact_phase_hours": g["contact_phase_hours"],
        "offer_ttl_hours": g["offer_ttl_hours"],
        "reapply_cooling_days": g["reapply_cooling_days"],
        "survey_valid_days": g["survey_valid_days"],
        "doc_buffer_minutes": g["doc_buffer_minutes"],
        "current_policy_version": g["current_policy_version"],
        "intake_posture": g["intake_posture"],
        "occupied_slots": calc.occupied_slots(),
        "waiting_count": calc.waiting_count(),
        "promotion_epoch": g["promotion_epoch"],
    })
    return d


def participant(p):
    d = _base(p)
    d.update({
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"].isoformat(),
        "phone": p["phone"],
        "address": p["address"],
        "primary_language": p["primary_language"],
        "referral_source": p["referral_source"],
        "age_band": p["age_band"],
        "lives_alone": p["lives_alone"],
        "mobility": p["mobility"],
        "cognitive_concern": p["cognitive_concern"],
        "chronic_conditions_count": p["chronic_conditions_count"],
        "recent_hospitalization": p["recent_hospitalization"],
        "recent_bereavement": p["recent_bereavement"],
        "acuity_score": p["acuity_score"],
        "acuity_tier": p["acuity_tier"],
        "rolling_acuity_score": p["rolling_acuity_score"],
        "rolling_acuity_tier": p["rolling_acuity_tier"],
        "effective_acuity_tier": calc.effective_tier(p),
        "status": p["status"],
        "consecutive_no_answer_count": p["consecutive_no_answer_count"],
        "open_escalation_id": p["open_escalation_id"],
        "coverage_deficient": p["coverage_deficient"],
        "enrolled_at": fmt_dt(p["enrolled_at"]),
        "last_status_change_at": fmt_dt(p["last_status_change_at"]),
    })
    return d


def contact(c):
    d = _base(c)
    d.update({
        "participant_id": c["participant_id"],
        "full_name": c["full_name"],
        "phone": c["phone"],
        "relationship": c["relationship"],
        "contact_rank": c["contact_rank"],
        "accepts_24h": c["accepts_24h"],
        "status": c["status"],
    })
    return d


def waitlist_entry(e):
    d = _base(e)
    d.update({
        "participant_id": e["participant_id"],
        "status": e["status"],
        "waitlist_entered_at": fmt_dt(e["waitlist_entered_at"]),
        "offered_at": fmt_dt(e["offered_at"]),
        "offer_expires_at": fmt_dt(e["offer_expires_at"]),
        "declines_count": e["declines_count"],
        "expires_count": e["expires_count"],
        "priority_score_at_offer": e["priority_score_at_offer"],
        "removal_reason": e["removal_reason"],
    })
    return d


def volunteer(v):
    d = _base(v)
    windowed, streak_adj, tier, cap = calc.reliability(v)
    d.update({
        "full_name": v["full_name"],
        "phone": v["phone"],
        "languages": list(v["languages"]),
        "max_weekly_minutes": v["max_weekly_minutes"],
        "status": v["status"],
        "reliability_windowed": windowed,
        "reliability_streak_adj": streak_adj,
        "reliability_tier": tier,
        "max_concurrent_assignments": cap,
        "current_week_minutes": calc.current_week_minutes(v),
    })
    return d


def availability_window(w):
    d = _base(w)
    d.update({
        "volunteer_id": w["volunteer_id"],
        "weekday": w["weekday"],
        "window_start": w["window_start"],
        "window_end": w["window_end"],
        "effective_from": w["effective_from"].isoformat(),
        "effective_to": w["effective_to"].isoformat() if w["effective_to"] else None,
    })
    return d


def training_record(r):
    d = _base(r)
    d.update({
        "volunteer_id": r["volunteer_id"],
        "module": r["module"],
        "completed_at": fmt_dt(r["completed_at"]),
        "valid_until": fmt_dt(r["valid_until"]),
        "status": calc.training_status(r),
    })
    return d


def agreement(a):
    d = _base(a)
    d.update({
        "volunteer_id": a["volunteer_id"],
        "policy_version": a["policy_version"],
        "signed_at": fmt_dt(a["signed_at"]),
        "valid_until": fmt_dt(a["valid_until"]),
        "status": a["status"],
    })
    return d


def schedule(s):
    d = _base(s)
    d.update({
        "participant_id": s["participant_id"],
        "weekday": s["weekday"],
        "window_start": s["window_start"],
        "window_end": s["window_end"],
        "status": s["status"],
    })
    return d


def assignment(a):
    d = _base(a)
    d.update({
        "participant_id": a["participant_id"],
        "volunteer_id": a["volunteer_id"],
        "scheduled_date": a["scheduled_date"].isoformat(),
        "window_start": a["window_start"],
        "window_end": a["window_end"],
        "source": a["source"],
        "escalation_id": a["escalation_id"],
        "rescheduled_from_id": a["rescheduled_from_id"],
        "status": a["status"],
        "cancel_reason": a["cancel_reason"],
    })
    return d


def call_log(lg):
    d = _base(lg)
    d.update({
        "assignment_id": lg["assignment_id"],
        "called_at": fmt_dt(lg["called_at"]),
        "duration_seconds": lg["duration_seconds"],
        "outcome": lg["outcome"],
        "concern_level": lg["concern_level"],
        "concern_categories": list(lg["concern_categories"]),
        "concern_flag": lg["concern_flag"],
        "follow_up_needed": lg["follow_up_needed"],
        "follow_up_plan": lg["follow_up_plan"],
        "supervisor_notified": lg["supervisor_notified"],
        "notes": lg["notes"],
    })
    return d


def escalation(e):
    d = _base(e)
    d.update({
        "participant_id": e["participant_id"],
        "trigger_type": e["trigger_type"],
        "stage": e["stage"],
        "opened_by_user_id": e["opened_by_user_id"],
        "opened_at": fmt_dt(e["opened_at"]),
        "stage_entered_at": fmt_dt(e["stage_entered_at"]),
        "retry_assignment_id": e["retry_assignment_id"],
        "supersedes_escalation_id": e["supersedes_escalation_id"],
        "contact_attempts": [
            {"contact_id": att["contact_id"], "outcome": att["outcome"],
             "attempted_at": fmt_dt(att["attempted_at"])}
            for att in e["contact_attempts"]
        ],
        "resolution_note": e["resolution_note"],
    })
    return d


def welfare_check(w):
    d = _base(w)
    d.update({
        "escalation_id": w["escalation_id"],
        "participant_id": w["participant_id"],
        "status": w["status"],
        "disposition": w["disposition"],
        "requested_at": fmt_dt(w["requested_at"]),
        "dispatched_at": fmt_dt(w["dispatched_at"]),
        "completed_at": fmt_dt(w["completed_at"]),
        "responder_note": w["responder_note"],
    })
    return d


def referral(r):
    d = _base(r)
    d.update({
        "participant_id": r["participant_id"],
        "source_call_log_id": r["source_call_log_id"],
        "escalation_id": r["escalation_id"],
        "service_type": r["service_type"],
        "priority": r["priority"],
        "status": r["status"],
        "submitted_at": fmt_dt(r["submitted_at"]),
        "sla_due_at": fmt_dt(r["sla_due_at"]),
        "overdue": calc.referral_overdue(r),
        "decline_reason": r["decline_reason"],
    })
    return d


def survey(s):
    d = _base(s)
    d.update({
        "participant_id": s["participant_id"],
        "period_month": s["period_month"],
        "issued_at": fmt_dt(s["issued_at"]),
        "status": s["status"],
        "items": list(s["items"]) if s["items"] is not None else None,
        "survey_mean": s["survey_mean"],
    })
    return d


def outcome_report(r):
    d = _base(r)
    d.update({
        "program_id": r["program_id"],
        "period_month": r["period_month"],
        "status": r["status"],
        "calls_scheduled": r["calls_scheduled"],
        "calls_completed": r["calls_completed"],
        "completion_rate": r["completion_rate"],
        "escalations_opened": r["escalations_opened"],
        "escalations_resolved": r["escalations_resolved"],
        "referrals_submitted": r["referrals_submitted"],
        "unique_participants_reached": r["unique_participants_reached"],
        "satisfaction_index": r["satisfaction_index"],
    })
    return d
