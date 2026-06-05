"""Serialize internal records into the API view (PRD §2.4 common fields plus
each entity's declared fields). compliance_status is derived at read time.
"""
from util import iso
import domain


def _common(rec):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if "version" in rec:  # non-append-only entities carry updated_at + version
        out["updated_at"] = iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def volunteer(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "email": rec["email"],
        "gender": rec["gender"],
        "home_zip": rec["home_zip"],
        "interest_tags": rec["interest_tags"],
        "max_weekly_hours": rec["max_weekly_hours"],
        "status": rec["status"],
        "active_match_count": rec["active_match_count"],
        "cleared_check_id": rec["cleared_check_id"],
    })
    return out


def background_check(rec):
    out = _common(rec)
    out.update({
        "volunteer_id": rec["volunteer_id"],
        "check_type": rec["check_type"],
        "submitted_at": iso(rec["submitted_at"]),
        "valid_until": iso(rec["valid_until"]),
        "adjudicated_at": iso(rec["adjudicated_at"]),
        "adverse_findings": rec["adverse_findings"],
        "status": rec["status"],
    })
    return out


def guardian(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "email": rec["email"],
        "consent_on_file": rec["consent_on_file"],
    })
    return out


def child(rec):
    out = _common(rec)
    out.update({
        "guardian_id": rec["guardian_id"],
        "first_name": rec["first_name"],
        "age": rec["age"],
        "gender": rec["gender"],
        "home_zip": rec["home_zip"],
        "interest_tags": rec["interest_tags"],
        "requires_same_gender": rec["requires_same_gender"],
        "status": rec["status"],
        "open_proposal_id": rec["open_proposal_id"],
    })
    return out


def match_proposal(rec):
    out = _common(rec)
    out.update({
        "child_id": rec["child_id"],
        "volunteer_id": rec["volunteer_id"],
        "compatibility_score": rec["compatibility_score"],
        "candidate_pool_size": rec["candidate_pool_size"],
        "status": rec["status"],
        "decline_reason": rec["decline_reason"],
    })
    return out


def match(rec):
    out = _common(rec)
    out.update({
        "child_id": rec["child_id"],
        "volunteer_id": rec["volunteer_id"],
        "proposal_id": rec["proposal_id"],
        "relationship_status": rec["relationship_status"],
        "compliance_status": domain.compliance_status(rec),
        "confirmed_at": iso(rec["confirmed_at"]),
        "activated_at": iso(rec["activated_at"]),
        "last_activity_at": iso(rec["last_activity_at"]),
        "last_contact_at": iso(rec["last_contact_at"]),
        "total_mentoring_minutes": rec["total_mentoring_minutes"],
        "closure_reason": rec["closure_reason"],
    })
    return out


def match_meeting(rec):
    out = _common(rec)
    out.update({
        "match_id": rec["match_id"],
        "scheduled_start": iso(rec["scheduled_start"]),
        "scheduled_end": iso(rec["scheduled_end"]),
        "location": rec["location"],
        "status": rec["status"],
        "outcome_notes": rec["outcome_notes"],
    })
    return out


def activity_log(rec):
    out = _common(rec)
    out.update({
        "match_id": rec["match_id"],
        "occurred_at": iso(rec["occurred_at"]),
        "duration_minutes": rec["duration_minutes"],
        "activity_type": rec["activity_type"],
        "status": rec["status"],
    })
    return out


def supervision_contact(rec):
    out = _common(rec)
    out.update({
        "match_id": rec["match_id"],
        "due_at": iso(rec["due_at"]),
        "contacted_at": iso(rec["contacted_at"]),
        "party": rec["party"],
        "concern_flag": rec["concern_flag"],
        "status": rec["status"],
    })
    return out


def exit_transition(rec):
    out = _common(rec)
    out.update({
        "match_id": rec["match_id"],
        "exit_type": rec["exit_type"],
        "initiated_by": rec["initiated_by"],
        "reason_code": rec["reason_code"],
        "status": rec["status"],
        "survey_required": rec["survey_required"],
    })
    return out


def outcome_survey(rec):
    out = _common(rec)
    out.update({
        "match_id": rec["match_id"],
        "exit_transition_id": rec["exit_transition_id"],
        "relationship_quality": rec["relationship_quality"],
        "child_outcome": rec["child_outcome"],
        "would_rematch": rec["would_rematch"],
        "composite_score": rec["composite_score"],
        "outcome_band": rec["outcome_band"],
    })
    return out
