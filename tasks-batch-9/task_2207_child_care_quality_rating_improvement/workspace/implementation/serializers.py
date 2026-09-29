"""Resource serializers. Common fields per PRD §2.4."""

from datetime import datetime
from decimal import Decimal

import store

COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "standard_domain": ["domain_code", "block_level", "max_points", "block_min_points",
                        "weight", "observation_linked", "min_composite_for_block"],
    "provider": ["legal_name", "license_number", "county_code", "region_code",
                 "licensed_capacity", "active_staff_fte", "weekly_onsite_cap_hours",
                 "status", "enrolled_on", "current_rating_cycle_id", "current_tier",
                 "credential_compliance_pct", "reimbursement_adjustment_cents",
                 "public_listing_visible"],
    "rating_cycle": ["provider_id", "cycle_type", "opened_on", "status", "publication_status",
                     "observation_composite", "reliability_pct", "domain_points",
                     "block_clearance", "highest_block_cleared", "weighted_total",
                     "points_tier", "awarded_tier", "score_variant", "awarded_on",
                     "awarded_by_user_id", "effective_date", "expires_on", "validity_months",
                     "rerating_window_opens_on", "published_at", "published_snapshot",
                     "appeal_adjusted", "supersedes_cycle_id", "superseded_by_cycle_id"],
    "self_assessment": ["rating_cycle_id", "claimed_points", "documentation", "verified_points",
                        "documented_domains", "status", "return_count", "verified_on"],
    "staff_credential": ["provider_id", "staff_registry_id", "role_type", "credential_level",
                         "fte", "employment_status", "registry_status", "verified_on",
                         "expires_on"],
    "observer": ["full_name", "tool_code", "anchor_agreement_pct",
                 "reliability_certified_until", "status"],
    "observation_visit": ["rating_cycle_id", "lead_observer_id", "secondary_observer_id",
                          "window_start", "window_end", "status", "composite",
                          "reliability_pct", "rescore_count", "finalized_on"],
    "observation_score": ["observation_visit_id", "observer_id", "subscale_code", "raw_score",
                          "attempt_no", "is_current"],
    "appeal": ["rating_cycle_id", "grounds", "narrative", "filed_on", "status",
               "info_request_count", "reviewer_user_id", "adjusted_tier", "decided_on"],
    "data_dispute": ["rating_cycle_id", "disputed_field", "claimed_value", "linked_appeal_id",
                     "status", "triage_round", "filed_on", "resolved_on"],
    "improvement_grant": ["provider_id", "rating_cycle_id", "awarded_amount_cents",
                          "spend_deadline", "committed_cents", "reimbursed_cents",
                          "available_cents", "category_spend_cents", "status",
                          "compliance_status", "recovery_amount_cents"],
    "grant_expenditure": ["improvement_grant_id", "category", "amount_cents", "invoice_date",
                          "status", "reimbursable_cents", "disallowed_cents"],
    "coaching_allocation": ["provider_id", "funding_grant_id", "coach_user_id", "funding_source",
                            "period_start", "period_end", "allocated_hours",
                            "hourly_rate_cents", "base_hours_cost_cents", "admin_fee_cents",
                            "total_cost_cents", "spend_cap_cents", "scheduled_hours",
                            "delivered_hours", "remaining_hours", "status"],
    "coaching_session": ["coaching_allocation_id", "scheduled_start", "scheduled_end",
                         "scheduled_hours", "delivered_hours", "iso_week_key", "status"],
    "subsidy_claim": ["provider_id", "rating_cycle_id", "service_month", "child_days",
                      "base_amount_cents", "tier_multiplier_applied", "reimbursement_cents",
                      "variant_applied", "status", "paid_on"],
}

# ObservationScore is deliberately leaner: id + created_at only (PRD §2.4).
LEAN = {"observation_score"}


def _value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return store.fmt_ts(value)
    if isinstance(value, dict):
        return {k: _value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_value(v) for v in value]
    return value


def dump(kind, rec, extra=None):
    if rec is None:
        return None
    out = {"id": rec["id"], "created_at": store.fmt_ts(rec["created_at"])}
    if kind not in LEAN:
        out["updated_at"] = store.fmt_ts(rec["updated_at"])
        out["version"] = rec["version"]
    for field in FIELDS[kind]:
        out[field] = _value(rec.get(field))
    if extra:
        for key, value in extra.items():
            out[key] = _value(value)
    return out


def maker(kind):
    def _dump(rec):
        return dump(kind, rec)
    return _dump
