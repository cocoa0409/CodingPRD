"""Resource serialization. Derived fields are recomputed at read time."""
from util import fmt_dt, money, ratio

from services import calc


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def program(row):
    out = {
        "name": row["name"],
        "fiscal_quarter": row["fiscal_quarter"],
        "status": row["status"],
        "posture": calc.posture(row),
        "incentive_budget_usd": money(row["incentive_budget_usd"]),
        "incentive_committed_usd": money(calc.incentive_committed(row)),
        "incentive_paid_usd": money(calc.incentive_paid(row)),
        "interview_incentive_cap_usd": money(row["interview_incentive_cap_usd"]),
        "min_deal_value_usd": money(row["min_deal_value_usd"]),
        "required_question_keys": list(row["required_question_keys"]),
        "guide_version": row["guide_version"],
        "max_open_interviews_per_analyst": row["max_open_interviews_per_analyst"],
        "independence_mode": row["independence_mode"],
    }
    out.update(_common(row))
    return out


def competitor(row):
    published, ratified, rate = calc.competitor_derived(row)
    out = {
        "program_id": row["program_id"],
        "name": row["name"],
        "tier": row["tier"],
        "status": row["status"],
        "published_battlecard_count": published,
        "ratified_loss_count": ratified,
        "win_rate_vs": ratio(rate) if rate is not None else None,
    }
    out.update(_common(row))
    return out


def deal(row):
    out = {
        "program_id": row["program_id"],
        "crm_deal_ref": row["crm_deal_ref"],
        "outcome": row["outcome"],
        "acr_usd": money(row["acr_usd"]),
        "close_date": fmt_dt(row["close_date"]),
        "segment": row["segment"],
        "sales_rep_user_ref": row["sales_rep_user_ref"],
        "primary_competitor_id": row.get("primary_competitor_id"),
        "sampling_frame_id": row.get("sampling_frame_id"),
        "stratum": row.get("stratum"),
        "selection_rank_score": ratio(row["selection_rank_score"])
        if row.get("selection_rank_score") is not None else None,
        "research_status": row["research_status"],
        "attribution_status": row["attribution_status"],
        "interview_coverage_count": calc.interview_coverage_count(row),
    }
    out.update(_common(row))
    return out


def analyst(row):
    open_count, minutes = calc.analyst_derived(row)
    out = {
        "program_id": row["program_id"],
        "full_name": row["full_name"],
        "linked_user_ref": row["linked_user_ref"],
        "employment_type": row["employment_type"],
        "sales_org_member": row["sales_org_member"],
        "certified_until": fmt_dt(row["certified_until"]),
        "status": row["status"],
        "open_interview_count": open_count,
        "committed_minutes": minutes,
    }
    out.update(_common(row))
    return out


def buyer_contact(row):
    count, last_end = calc.contact_derived(row)
    out = {
        "deal_id": row["deal_id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "title_band": row["title_band"],
        "consent_status": row["consent_status"],
        "incentive_eligibility": row["incentive_eligibility"],
        "completed_interview_count": count,
        "last_completed_interview_end_at": fmt_dt(last_end),
    }
    out.update(_common(row))
    return out


def sampling_frame(row):
    out = {
        "program_id": row["program_id"],
        "label": row["label"],
        "window_start": fmt_dt(row["window_start"]),
        "window_end": fmt_dt(row["window_end"]),
        "quota_won": row["quota_won"],
        "quota_lost": row["quota_lost"],
        "quota_no_decision": row["quota_no_decision"],
        "selection_basis": row["selection_basis"],
        "status": row["status"],
        "selected_won_count": calc.selected_count(row, "WON"),
        "selected_lost_count": calc.selected_count(row, "LOST"),
        "selected_no_decision_count": calc.selected_count(row, "NO_DECISION"),
        "open_won_slots": calc.open_slots(row, "WON"),
        "open_lost_slots": calc.open_slots(row, "LOST"),
        "open_no_decision_slots": calc.open_slots(row, "NO_DECISION"),
        "coverage_ratio": ratio(calc.coverage_ratio(row)),
    }
    out.update(_common(row))
    return out


def interview(row):
    out = {
        "deal_id": row["deal_id"],
        "buyer_contact_id": row["buyer_contact_id"],
        "analyst_id": row["analyst_id"],
        "scheduled_start_at": fmt_dt(row["scheduled_start_at"]),
        "scheduled_end_at": fmt_dt(row["scheduled_end_at"]),
        "actual_start_at": fmt_dt(row.get("actual_start_at")),
        "actual_end_at": fmt_dt(row.get("actual_end_at")),
        "status": row["status"],
        "incentive_status": row["incentive_status"],
        "incentive_provisional_usd": money(row["incentive_provisional_usd"]),
        "incentive_final_usd": money(row["incentive_final_usd"])
        if row.get("incentive_final_usd") is not None else None,
        "guide_version_pinned": row["guide_version_pinned"],
        "required_question_keys_pinned": list(row["required_question_keys_pinned"]),
        "coverage_complete": row["coverage_complete"],
        "reschedule_count": row["reschedule_count"],
    }
    out.update(_common(row))
    return out


def interview_response(row):
    # PRD 2.4: append-only evidence carries only id and created_at.
    return {
        "id": row["id"],
        "interview_id": row["interview_id"],
        "question_key": row["question_key"],
        "verbatim_text": row["verbatim_text"],
        "rating": row.get("rating"),
        "competitor_name_verbatim": row.get("competitor_name_verbatim"),
        "recorded_at": fmt_dt(row["recorded_at"]),
        "created_at": fmt_dt(row["created_at"]),
    }


def loss_reason(row):
    out = {
        "program_id": row["program_id"],
        "parent_reason_id": row.get("parent_reason_id"),
        "code": row["code"],
        "label": row["label"],
        "depth": row["depth"],
        "is_leaf": calc.is_leaf(row),
        "status": row["status"],
        "ratified_attribution_count": calc.reason_ratified_attribution_count(row),
    }
    out.update(_common(row))
    return out


def loss_attribution(row):
    out = {
        "deal_id": row["deal_id"],
        "primary_reason_id": row["primary_reason_id"],
        "secondary_reason_id": row.get("secondary_reason_id"),
        "authored_by_analyst_id": row["authored_by_analyst_id"],
        "ratified_by_analyst_id": row.get("ratified_by_analyst_id"),
        "weight_primary": money(row["weight_primary"]),
        "weight_secondary": money(row["weight_secondary"]),
        "status": row["status"],
        "confidence_score": money(row["confidence_score"]),
    }
    out.update(_common(row))
    return out


def battlecard(row):
    (pre, final), (approved, conditional, rejected, corroborated), \
        (assigned, trained, rate) = calc.battlecard_derived(row)
    out = {
        "competitor_id": row["competitor_id"],
        "title": row["title"],
        "version_label": row["version_label"],
        "status": row["status"],
        "risk_index_pre": money(pre),
        "risk_index_final": money(final),
        "approved_claim_count": approved,
        "conditional_claim_count": conditional,
        "rejected_claim_count": rejected,
        "corroborated_claim_count": corroborated,
        "assigned_count": assigned,
        "trained_count": trained,
        "adoption_rate": ratio(rate),
        "published_at": fmt_dt(row.get("published_at")),
        "reopen_count": row["reopen_count"],
    }
    out.update(_common(row))
    return out


def battlecard_claim(row):
    out = {
        "battlecard_id": row["battlecard_id"],
        "claim_text": row["claim_text"],
        "claim_type": row["claim_type"],
        "evidence_response_ids": list(row["evidence_response_ids"]),
        "substantiation_score": money(row["substantiation_score"]),
        "substantiation_level": row["substantiation_level"],
        "risk_class": row["risk_class"],
        "legal_status": row["legal_status"],
        "conditions_note": row.get("conditions_note"),
        "decided_at": fmt_dt(row.get("decided_at")),
    }
    out.update(_common(row))
    return out


def product_gap(row):
    competitor_id, linked, affected, impact, band = calc.gap_current_metrics(row)
    out = {
        "program_id": row["program_id"],
        "source_response_id": row["source_response_id"],
        "additional_response_ids": list(row.get("additional_response_ids") or []),
        "gap_summary": row["gap_summary"],
        "derived_competitor_id": competitor_id,
        "linked_deal_count": linked,
        "affected_acr_usd": money(affected),
        "impact_score": money(impact),
        "roadmap_priority_band": band,
        "status": row["status"],
        "roadmap_epic_ref": row.get("roadmap_epic_ref"),
    }
    out.update(_common(row))
    return out


def enablement_assignment(row):
    out = {
        "battlecard_id": row["battlecard_id"],
        "sales_rep_user_ref": row["sales_rep_user_ref"],
        "assigned_at": fmt_dt(row["assigned_at"]),
        "due_at": fmt_dt(row["due_at"]),
        "status": row["status"],
        "quiz_score": row.get("quiz_score"),
        "attempt_count": row["attempt_count"],
        "completed_at": fmt_dt(row.get("completed_at")),
    }
    out.update(_common(row))
    return out
