"""Explicit per-entity serializers: exact output field sets, no internals."""

from util import fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def jurisdiction_out(r):
    out = _common(r)
    out.update({
        "parent_jurisdiction_id": r["parent_jurisdiction_id"],
        "code": r["code"],
        "name": r["name"],
        "level": r["level"],
        "eviction_notice_days": r["eviction_notice_days"],
        "habitability_repair_days": r["habitability_repair_days"],
        "deposit_cap_months": r["deposit_cap_months"],
        "deposit_interest_required": r["deposit_interest_required"],
        "deposit_interest_rate_pct": r["deposit_interest_rate_pct"],
    })
    return out


def script_out(r):
    out = _common(r)
    out.update({
        "jurisdiction_id": r["jurisdiction_id"],
        "issue_category": r["issue_category"],
        "version_no": r["version_no"],
        "body": r["body"],
        "effective_from": fmt_dt(r["effective_from"]),
        "effective_until": fmt_dt(r["effective_until"]),
        "supersedes_script_id": r["supersedes_script_id"],
        "author_counselor_id": r["author_counselor_id"],
        "reviewer_counselor_id": r["reviewer_counselor_id"],
        "status": r["status"],
    })
    return out


def resource_out(r):
    out = _common(r)
    out.update({
        "jurisdiction_id": r["jurisdiction_id"],
        "issue_category": r["issue_category"],
        "title": r["title"],
        "body": r["body"],
        "language_code": r["language_code"],
        "linked_script_id": r["linked_script_id"],
        "status": r["status"],
    })
    return out


def counselor_out(r):
    out = _common(r)
    out.update({
        "display_name": r["display_name"],
        "languages": list(r["languages"]),
        "certified_jurisdiction_codes": list(r["certified_jurisdiction_codes"]),
        "certified_categories": list(r["certified_categories"]),
        "certification_expires_at": fmt_dt(r["certification_expires_at"]),
        "is_script_reviewer": r["is_script_reviewer"],
        "trained_script_ids": list(r["trained_script_ids"]),
        "status": r["status"],
    })
    return out


def interpreter_out(r):
    out = _common(r)
    out.update({
        "display_name": r["display_name"],
        "language_code": r["language_code"],
    })
    return out


def caller_out(r):
    out = _common(r)
    out.update({
        "alias": r["alias"],
        "phone": r["phone"],
        "preferred_language": r["preferred_language"],
        "channel": r["channel"],
        "accessibility_needs": list(r["accessibility_needs"]),
        "is_anonymous": r["is_anonymous"],
        "pii_purged": r["pii_purged"],
        "do_not_aggregate": r["do_not_aggregate"],
    })
    return out


def consent_out(r):
    out = _common(r)
    out.update({
        "caller_id": r["caller_id"],
        "consent_type": r["consent_type"],
        "status": r["status"],
        "granted_at": fmt_dt(r["granted_at"]),
        "expires_at": fmt_dt(r["expires_at"]),
        "revoked_at": fmt_dt(r["revoked_at"]),
    })
    return out


def session_out(r):
    out = _common(r)
    out.update({
        "caller_id": r["caller_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "issue_category": r["issue_category"],
        "triage_notes": r["triage_notes"],
        "counselor_id": r["counselor_id"],
        "interpreter_id": r["interpreter_id"],
        "scheduled_start_at": fmt_dt(r["scheduled_start_at"]),
        "scheduled_end_at": fmt_dt(r["scheduled_end_at"]),
        "actual_start_at": fmt_dt(r["actual_start_at"]),
        "actual_end_at": fmt_dt(r["actual_end_at"]),
        "queue_wait_seconds": r["queue_wait_seconds"],
        "session_status": r["session_status"],
        "interpretation_status": r["interpretation_status"],
        "pinned_script_id": r["pinned_script_id"],
        "failed_interpreter_ids": list(r["failed_interpreter_ids"]),
    })
    return out


def case_out(r):
    out = _common(r)
    out.update({
        "caller_id": r["caller_id"],
        "opened_from_session_id": r["opened_from_session_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "issue_category": r["issue_category"],
        "opened_by_counselor_id": r["opened_by_counselor_id"],
        "eviction_notice_date": r["eviction_notice_date"].isoformat() if r["eviction_notice_date"] else None,
        "notice_served_at": fmt_dt(r["notice_served_at"]),
        "habitability_reported_at": fmt_dt(r["habitability_reported_at"]),
        "deposit_amount_cents": r["deposit_amount_cents"],
        "monthly_rent_cents": r["monthly_rent_cents"],
        "deposit_days_held": r["deposit_days_held"],
        "legal_hold": r["legal_hold"],
        "priority_score": r["priority_score"],
        "urgency_tier": r["urgency_tier"],
        "score_variant": r["score_variant"],
        "verified_by_counselor_id": r["verified_by_counselor_id"],
        "missed_follow_up_count": r["missed_follow_up_count"],
        "required_follow_up_count": r["required_follow_up_count"],
        "escalation_level": r["escalation_level"],
        "last_escalated_at": fmt_dt(r["last_escalated_at"]),
        "deposit_exposure_cents": r["deposit_exposure_cents"],
        "closed_at": fmt_dt(r["closed_at"]),
        "status": r["status"],
    })
    return out


def note_out(r):
    # CaseNote is immutable: id + created_at only, no updated_at / version
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "counselor_id": r["counselor_id"],
        "body": r["body"],
        "is_confidential": r["is_confidential"],
        "system_generated": r["system_generated"],
        "created_at": fmt_dt(r["created_at"]),
    }


def follow_up_out(r):
    out = _common(r)
    out.update({
        "case_id": r["case_id"],
        "scheduled_for": fmt_dt(r["scheduled_for"]),
        "status": r["status"],
        "completed_at": fmt_dt(r["completed_at"]),
        "outcome": r["outcome"],
        "auto_created": r["auto_created"],
        "required_count_at_schedule": r["required_count_at_schedule"],
    })
    return out


def org_out(r, current_week_reserved):
    out = _common(r)
    out.update({
        "name": r["name"],
        "covered_jurisdiction_codes": list(r["covered_jurisdiction_codes"]),
        "accepted_categories": list(r["accepted_categories"]),
        "weekly_capacity": r["weekly_capacity"],
        "current_week_reserved": current_week_reserved,
        "status": r["status"],
    })
    return out


def referral_out(r):
    out = _common(r)
    out.update({
        "case_id": r["case_id"],
        "referral_type": r["referral_type"],
        "legal_aid_org_id": r["legal_aid_org_id"],
        "self_help_resource_id": r["self_help_resource_id"],
        "status": r["status"],
        "sla_dispatch_by": fmt_dt(r["sla_dispatch_by"]),
        "accept_by": fmt_dt(r["accept_by"]),
        "dispatched_at": fmt_dt(r["dispatched_at"]),
        "declined_org_ids": list(r["declined_org_ids"]),
        "cancel_reason": r["cancel_reason"],
    })
    return out


def policy_out(r):
    out = _common(r)
    out.update({
        "jurisdiction_id": r["jurisdiction_id"],
        "issue_category": r["issue_category"],
        "retention_days": r["retention_days"],
        "status": r["status"],
    })
    return out


def purge_job_out(r):
    out = _common(r)
    out.update({
        "caller_id": r["caller_id"],
        "status": r["status"],
        "created_by_sweep": r["created_by_sweep"],
        "executed_at": fmt_dt(r["executed_at"]),
        "blocked_reason": r["blocked_reason"],
    })
    return out
