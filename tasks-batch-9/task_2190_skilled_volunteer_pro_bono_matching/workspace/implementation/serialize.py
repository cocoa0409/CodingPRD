"""Resource representations. Computed fields are derived at read time."""
import calc
import store as S
from calc import dec, rnd


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    if "updated_at" in row:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def partner_org(row):
    capacity_class, ceiling = calc.partner_capacity(row["annual_budget_usd"])
    return _common(
        row,
        {
            "name": row["name"],
            "contact_email": row["contact_email"],
            "sector": row["sector"],
            "annual_budget_usd": rnd(row["annual_budget_usd"], 2),
            "capacity_class": capacity_class,
            "max_concurrent_engagements": ceiling,
            "open_engagement_count": calc.partner_open_engagements(row["id"]),
            "satisfaction_index": row["satisfaction_index"],
            "satisfaction_sample_size": row["satisfaction_sample_size"],
            "status": row["status"],
            "probation_reason": row["probation_reason"],
            "suspended_at": row["suspended_at"],
        },
    )


def program_cycle(row):
    metrics = calc.cycle_metrics(row)
    return _common(
        row,
        {
            "cycle_code": row["cycle_code"],
            "starts_at": row["starts_at"],
            "ends_at": row["ends_at"],
            "capacity_slot_total": row["capacity_slot_total"],
            "slots_committed": metrics["slots_committed"],
            "slots_reserved": metrics["slots_reserved"],
            "slots_available": metrics["slots_available"],
            "utilization_ratio": metrics["utilization_ratio"],
            "posture": metrics["posture"],
            "last_recalculated_at": row["last_recalculated_at"],
            "recalc_epoch": row["recalc_epoch"],
        },
    )


def active_revision_no(request_id):
    best = 0
    for scope in S.where("scope_definitions", project_request_id=request_id):
        if scope["status"] == "APPROVED":
            best = max(best, int(scope["revision_no"]))
    return best


def pinned_scope(engagement):
    return S.get("scope_definitions", engagement["scope_definition_id"])


def project_request(row):
    return _common(
        row,
        {
            "partner_org_id": row["partner_org_id"],
            "cycle_id": row["cycle_id"],
            "title": row["title"],
            "discipline": row["discipline"],
            "required_skill_code": row["required_skill_code"],
            "min_proficiency": row["min_proficiency"],
            "requested_hours": rnd(row["requested_hours"], 2),
            "urgency": row["urgency"],
            "status": row["status"],
            "active_scope_revision_no": active_revision_no(row["id"]),
            "rescope_count": row["rescope_count"],
            "failed_match_rounds": row["failed_match_rounds"],
            "closed_at": row["closed_at"],
        },
    )


def scope_definition(row):
    deliverables = S.where("deliverables", scope_definition_id=row["id"])
    active = [d for d in deliverables if d["review_status"] != "WAIVED"]
    return _common(
        row,
        {
            "project_request_id": row["project_request_id"],
            "supersedes_scope_id": row["supersedes_scope_id"],
            "revision_no": row["revision_no"],
            "authored_by_user_id": row["authored_by_user_id"],
            "estimated_hours": rnd(row["estimated_hours"], 2),
            "complexity_factor": rnd(row["complexity_factor"], 2),
            "confidentiality_tier": row["confidentiality_tier"],
            "ip_disposition": row["ip_disposition"],
            "deliverable_weight_total_pct": calc.deliverable_weight_total(row["id"]),
            "deliverable_count": len(active),
            "status": row["status"],
            "approved_at": row["approved_at"],
            "approved_by_user_id": row["approved_by_user_id"],
        },
    )


def deliverable(row):
    return _common(
        row,
        {
            "scope_definition_id": row["scope_definition_id"],
            "title": row["title"],
            "sequence_no": row["sequence_no"],
            "weight_pct": rnd(row["weight_pct"], 2),
            "hours_estimate": rnd(row["hours_estimate"], 2),
            "acceptance_criteria": row["acceptance_criteria"],
            "review_status": row["review_status"],
            "review_score": row["review_score"],
            "waived_reason": row["waived_reason"],
        },
    )


def volunteer(row):
    decay, lifetime = calc.reliability(row["id"])
    return _common(
        row,
        {
            "full_name": row["full_name"],
            "email": row["email"],
            "professional_rate_usd_per_hour": rnd(
                row["professional_rate_usd_per_hour"], 2
            ),
            "seniority": row["seniority"],
            "weekly_hours_cap": row["weekly_hours_cap"],
            "credential_verified_at": row["credential_verified_at"],
            "reliability_score": decay,
            "reliability_score_lifetime": lifetime,
            "terminal_engagement_count": len(
                calc.volunteer_terminal_engagements(row["id"])
            ),
            "open_engagement_count": calc.volunteer_open_engagements(row["id"]),
            "lifetime_valued_usd": calc.lifetime_valued_usd(row["id"]),
            "status": row["status"],
            "pause_reason": row["pause_reason"],
        },
    )


def skill_profile(row):
    return _common(
        row,
        {
            "volunteer_id": row["volunteer_id"],
            "skill_code": row["skill_code"],
            "proficiency": row["proficiency"],
            "years_experience": rnd(row["years_experience"], 1),
            "verified": row["verified"],
            "verified_at": row["verified_at"],
        },
    )


def availability_window(row):
    metrics = calc.window_metrics(row)
    return _common(
        row,
        {
            "volunteer_id": row["volunteer_id"],
            "starts_at": row["starts_at"],
            "ends_at": row["ends_at"],
            "window_kind": row["window_kind"],
            "hours_offered": rnd(row["hours_offered"], 2),
            "hours_committed": metrics["hours_committed"],
            "hours_remaining": metrics["hours_remaining"],
            "status": metrics["status"],
        },
    )


def match_offer(row):
    return _common(
        row,
        {
            "project_request_id": row["project_request_id"],
            "volunteer_id": row["volunteer_id"],
            "scope_definition_id": row["scope_definition_id"],
            "availability_window_id": row["availability_window_id"],
            "round_no": row["round_no"],
            "match_score": row["match_score"],
            "reserved_hours": rnd(row["reserved_hours"], 2),
            "offered_at": row["offered_at"],
            "expires_at": row["expires_at"],
            "status": row["status"],
            "decline_reason": row["decline_reason"],
            "withdraw_reason": row["withdraw_reason"],
            "responded_at": row["responded_at"],
        },
    )


def engagement(row):
    pct, level = calc.creep(row)
    return _common(
        row,
        {
            "match_offer_id": row["match_offer_id"],
            "project_request_id": row["project_request_id"],
            "volunteer_id": row["volunteer_id"],
            "scope_definition_id": row["scope_definition_id"],
            "cycle_id": row["cycle_id"],
            "availability_window_id": row["availability_window_id"],
            "committed_hours": rnd(row["committed_hours"], 2),
            "approved_hours": calc.approved_hours(row),
            "scope_creep_pct": pct,
            "creep_escalation_level": level,
            "work_status": row["work_status"],
            "valuation_status": row["valuation_status"],
            "quality_gate": row["quality_gate"],
            "confidentiality_attested": row["confidentiality_attested"],
            "handoff_artifact_count": row["handoff_artifact_count"],
            "missed_checkin_count": calc.engagement_missed_checkins(row["id"]),
            "handoff_at": row["handoff_at"],
            "terminated_at": row["terminated_at"],
            "termination_reason": row["termination_reason"],
        },
    )


def agreement(row):
    return _common(
        row,
        {
            "engagement_id": row["engagement_id"],
            "ip_disposition": row["ip_disposition"],
            "confidentiality_tier": row["confidentiality_tier"],
            "indemnity_cap_usd": rnd(row["indemnity_cap_usd"], 2),
            "counter_round": row["counter_round"],
            "terms_revision_no": row["terms_revision_no"],
            "last_countered_by": row["last_countered_by"],
            "volunteer_signed_at": row["volunteer_signed_at"],
            "partner_signed_at": row["partner_signed_at"],
            "status": row["status"],
            "void_reason": row["void_reason"],
        },
    )


def milestone(row):
    return _common(
        row,
        {
            "engagement_id": row["engagement_id"],
            "sequence_no": row["sequence_no"],
            "due_at": row["due_at"],
            "checkin_status": row["checkin_status"],
            "held_at": row["held_at"],
            "reported_cumulative_hours": row["reported_cumulative_hours"],
            "variance_hours": row["variance_hours"],
            "escalation_raised": row["escalation_raised"],
            "waiver_reason": row["waiver_reason"],
        },
    )


def time_log(row):
    return _common(
        row,
        {
            "engagement_id": row["engagement_id"],
            "milestone_id": row["milestone_id"],
            "work_date": row["work_date"],
            "hours": rnd(row["hours"], 2),
            "activity_class": row["activity_class"],
            "rate_basis_usd": rnd(row["rate_basis_usd"], 2),
            "approved": row["approved"],
            "approved_at": row["approved_at"],
            "logged_by_user_id": row["logged_by_user_id"],
        },
    )


def scope_change_request(row):
    return _common(
        row,
        {
            "engagement_id": row["engagement_id"],
            "requested_by": row["requested_by"],
            "additional_hours": rnd(row["additional_hours"], 2),
            "additional_deliverable_count": row["additional_deliverable_count"],
            "justification": row["justification"],
            "projected_creep_pct": row["projected_creep_pct"],
            "decision_tier": row["decision_tier"],
            "status": row["status"],
            "decided_by_user_id": row["decided_by_user_id"],
            "decided_at": row["decided_at"],
            "resulting_scope_revision_no": row["resulting_scope_revision_no"],
        },
    )


def quality_review(row):
    return _common(
        row,
        {
            "engagement_id": row["engagement_id"],
            "reviewer_user_id": row["reviewer_user_id"],
            "round_no": row["round_no"],
            "scored_deliverable_count": row["scored_deliverable_count"],
            "weighted_score": row["weighted_score"],
            "outcome": row["outcome"],
            "status": row["status"],
            "rework_deadline_at": row["rework_deadline_at"],
            "decided_at": row["decided_at"],
        },
    )


def satisfaction_survey(row):
    return _common(
        row,
        {
            "engagement_id": row["engagement_id"],
            "partner_org_id": row["partner_org_id"],
            "submitted_at": row["submitted_at"],
            "score_expertise": row["score_expertise"],
            "score_responsiveness": row["score_responsiveness"],
            "score_deliverable_fit": row["score_deliverable_fit"],
            "would_recommend": row["would_recommend"],
            "composite_score": row["composite_score"],
            "counted_in_index": row["counted_in_index"],
        },
    )


def valuation_record(row):
    return _common(
        row,
        {
            "engagement_id": row["engagement_id"],
            "method": row["method"],
            "sequence_no": row["sequence_no"],
            "hours_included": rnd(row["hours_included"], 2),
            "rate_applied_usd": rnd(row["rate_applied_usd"], 2),
            "base_amount_usd": rnd(row["base_amount_usd"], 2),
            "admin_overhead_usd": rnd(row["admin_overhead_usd"], 2),
            "total_amount_usd": rnd(row["total_amount_usd"], 2),
            "variant_label": row["variant_label"],
            "superseded_at": row["superseded_at"],
            "posted_at": row["posted_at"],
        },
    )


def partner_summary(row):
    out = partner_org(row)
    pool = calc.satisfaction_pool(row["id"])
    surveys = []
    for survey in S.where("satisfaction_surveys", partner_org_id=row["id"]):
        surveys.append(
            {
                "id": survey["id"],
                "engagement_id": survey["engagement_id"],
                "composite_score": survey["composite_score"],
                "counted_in_index": survey["counted_in_index"],
                "submitted_at": survey["submitted_at"],
            }
        )
    out["survey_composite_scores"] = [s["composite_score"] for s in surveys]
    out["surveys"] = surveys
    out["eligible_survey_count"] = len(pool)
    return out
