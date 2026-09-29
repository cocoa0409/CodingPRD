"""Resource serializers.

Immutable event rows (ChannelPreferenceSignal, Touchpoint, NurtureSend,
BudgetLedgerEntry) deliberately omit `updated_at` and `version` (PRD 2.4).
"""

from db import fmt
from services import calc


def _audit(row):
    return {
        "created_at": fmt(row["created_at"]),
        "updated_at": fmt(row["updated_at"]),
        "version": row["version"],
    }


def program(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "fiscal_year": row["fiscal_year"],
        "attribution_model": row["attribution_model"],
        "pool_job_board_cents": row["pool_job_board_cents"],
        "pool_social_cents": row["pool_social_cents"],
        "pool_programmatic_cents": row["pool_programmatic_cents"],
        "flex_reserve_cents": row["flex_reserve_cents"],
        "send_quota_total": row["send_quota_total"],
        "send_quota_used": calc.send_quota_used(row),
        "committed_budget_cents": calc.committed_budget_cents(row),
        "available_budget_cents": calc.available_budget_cents(row),
        "brand_health_score": calc.brand_health_score(row),
        "last_attribution_recompute_at": fmt(row["last_attribution_recompute_at"]),
    }
    out.update(_audit(row))
    return out


def job_family(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "name": row["name"],
        "code": row["code"],
        "cpqa_target_cents": row["cpqa_target_cents"],
        "dedicated_budget_cents": row["dedicated_budget_cents"],
        "priority_rank": row["priority_rank"],
        "reserved_cents": calc.family_reserved_cents(row),
        "dedicated_available_cents": calc.family_available_cents(row),
    }
    out.update(_audit(row))
    return out


def channel(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "name": row["name"],
        "channel_type": row["channel_type"],
        "daily_capacity_cents": row["daily_capacity_cents"],
        "min_flight_days": row["min_flight_days"],
        "spent_cents": calc.channel_spent_cents(row),
        "credited_qualified_bp": calc.channel_credited_qualified_bp(row),
        "blended_target_cents": row["blended_target_cents"],
        "cpqa_cents": row["cpqa_cents"],
        "pacing_status": row["pacing_status"],
        "active_flight_count": calc.channel_active_flight_count(row),
        "idle_since": fmt(row["idle_since"]),
    }
    out.update(_audit(row))
    return out


def persona(row):
    out = {
        "id": row["id"],
        "job_family_id": row["job_family_id"],
        "name": row["name"],
        "mix_method": row["mix_method"],
        "research_window_days": row["research_window_days"],
        "state": row["state"],
        "channel_mix": [dict(item) for item in row["channel_mix"]],
        "mix_confidence_pct": row["mix_confidence_pct"],
        "signal_count": row["signal_count"],
        "revision_count": row["revision_count"],
        "drafted_by_user_id": row["drafted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "last_review_note": row["last_review_note"],
    }
    out.update(_audit(row))
    return out


def signal(row):
    return {
        "id": row["id"],
        "persona_id": row["persona_id"],
        "channel_id": row["channel_id"],
        "preference_score": row["preference_score"],
        "sample_size": row["sample_size"],
        "engagement_events": row["engagement_events"],
        "collected_at": fmt(row["collected_at"]),
        "created_at": fmt(row["created_at"]),
    }


def posting(row):
    metrics = calc.posting_conversion_metrics(row)
    out = {
        "id": row["id"],
        "job_family_id": row["job_family_id"],
        "title": row["title"],
        "title_word_count": row["title_word_count"],
        "responsibility_count": row["responsibility_count"],
        "benefit_count": row["benefit_count"],
        "pay_range_min_cents": row["pay_range_min_cents"],
        "pay_range_max_cents": row["pay_range_max_cents"],
        "eeo_statement_included": row["eeo_statement_included"],
        "superlative_claim_included": row["superlative_claim_included"],
        "substantiation_url": row["substantiation_url"],
        "content_status": row["content_status"],
        "compliance_status": row["compliance_status"],
        "optimization_score": row["optimization_score"],
        "apply_start_count": metrics["apply_start_count"],
        "submitted_count": metrics["submitted_count"],
        "qualified_count": metrics["qualified_count"],
        "conversion_rate_bp": metrics["conversion_rate_bp"],
        "optimized_by_user_id": row["optimized_by_user_id"],
        "cleared_by_user_id": row["cleared_by_user_id"],
        "suspended_reason": row["suspended_reason"],
    }
    out.update(_audit(row))
    return out


def flight(row):
    out = {
        "id": row["id"],
        "channel_id": row["channel_id"],
        "job_family_id": row["job_family_id"],
        "job_posting_id": row["job_posting_id"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "daily_cap_cents": row["daily_cap_cents"],
        "flight_days": row["flight_days"],
        "base_gross_cents": row["base_gross_cents"],
        "cost_tier": row["cost_tier"],
        "volume_discount_cents": row["volume_discount_cents"],
        "platform_fee_cents": row["platform_fee_cents"],
        "total_cost_cents": row["total_cost_cents"],
        "reserved_cents": row["reserved_cents"],
        "spent_cents": row["spent_cents"],
        "state": row["state"],
        "qualified_credit_bp": calc.flight_qualified_credit_bp(row),
        "release_reason": row["release_reason"],
        "activated_at": fmt(row["activated_at"]),
    }
    out.update(_audit(row))
    return out


def application(row):
    out = {
        "id": row["id"],
        "job_posting_id": row["job_posting_id"],
        "candidate_email": row["candidate_email"],
        "status": row["status"],
        "submitted_at": fmt(row["submitted_at"]),
        "screened_at": fmt(row["screened_at"]),
        "decided_at": fmt(row["decided_at"]),
        "attributed_credit_bp_total": row["attributed_credit_bp_total"],
        "eligible_touch_count": row["eligible_touch_count"],
        "attribution_model_applied": row["attribution_model_applied"],
    }
    out.update(_audit(row))
    return out


def touchpoint(row):
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "channel_id": row["channel_id"],
        "media_flight_id": row["media_flight_id"],
        "touch_type": row["touch_type"],
        "occurred_at": fmt(row["occurred_at"]),
        "media_cost_cents": row["media_cost_cents"],
        "credit_bp": row["credit_bp"],
        "created_at": fmt(row["created_at"]),
    }


def member(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "interest_job_family_id": row["interest_job_family_id"],
        "email": row["email"],
        "consent_status": row["consent_status"],
        "consent_token": row["consent_token"],
        "frequency_cap_per_30d": row["frequency_cap_per_30d"],
        "sent_count_total": calc.member_sent_count_total(row),
        "last_sent_at": fmt(calc.member_last_sent_at(row)),
        "consent_confirmed_at": fmt(row["consent_confirmed_at"]),
        "consent_changed_at": fmt(row["consent_changed_at"]),
    }
    out.update(_audit(row))
    return out


def campaign(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "job_family_id": row["job_family_id"],
        "name": row["name"],
        "max_sends": row["max_sends"],
        "state": row["state"],
        "scheduled_for": fmt(row["scheduled_for"]),
        "dispatched_at": fmt(row["dispatched_at"]),
    }
    out.update(calc.campaign_counters(row))
    out.update(_audit(row))
    return out


def send(row):
    return {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "member_id": row["member_id"],
        "outcome": row["outcome"],
        "evaluated_at": fmt(row["evaluated_at"]),
        "sent_at": fmt(row["sent_at"]),
        "window_send_count_at_eval": row["window_send_count_at_eval"],
        "sequence_no": row["sequence_no"],
        "created_at": fmt(row["created_at"]),
    }


def review(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "platform": row["platform"],
        "external_ref": row["external_ref"],
        "rating": row["rating"],
        "posted_at": fmt(row["posted_at"]),
        "response_due_at": fmt(row["response_due_at"]),
        "state": row["state"],
        "response_body": row["response_body"],
        "sla_status": calc.sla_status(row),
        "rejection_count": row["rejection_count"],
        "drafted_by_user_id": row["drafted_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "responded_at": fmt(row["responded_at"]),
    }
    out.update(_audit(row))
    return out


def presence(row):
    out = {
        "id": row["id"],
        "program_id": row["program_id"],
        "job_family_id": row["job_family_id"],
        "venue_code": row["venue_code"],
        "start_at": fmt(row["start_at"]),
        "end_at": fmt(row["end_at"]),
        "booth_cost_cents": row["booth_cost_cents"],
        "state": row["state"],
        "reserved_cents": row["reserved_cents"],
        "confirmed_at": fmt(row["confirmed_at"]),
    }
    out.update(_audit(row))
    return out


def ledger_entry(row):
    return {
        "id": row["id"],
        "program_id": row["program_id"],
        "job_family_id": row["job_family_id"],
        "bucket": row["bucket"],
        "entry_type": row["entry_type"],
        "delta_cents": row["delta_cents"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "reason": row["reason"],
        "sequence_no": row["sequence_no"],
        "created_at": fmt(row["created_at"]),
    }
