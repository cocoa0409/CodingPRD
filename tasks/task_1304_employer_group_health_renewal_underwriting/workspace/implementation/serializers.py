"""Entity serializers — only spec'd fields plus common system fields."""


def base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _pick(rec, keys):
    return {k: rec.get(k) for k in keys}


def case_json(c):
    out = base(c)
    out.update(_pick(c, [
        "group_name", "group_size", "sic_code", "state_code", "effective_date",
        "current_premium_annual", "current_renewal_date", "funding_type",
        "status", "assigned_underwriter_id", "broker_id", "credibility_factor",
        "blended_rate_cents", "manual_rate_cents", "experience_rate_cents",
        "rate_cap_pct", "is_rate_cap_applied",
    ]))
    return out


def broker_json(b):
    out = base(b)
    out.update(_pick(b, [
        "firm_name", "license_number", "state_code", "commission_pct", "status",
    ]))
    return out


def census_json(c):
    out = base(c)
    out.update(_pick(c, [
        "case_id", "submitted_at", "total_employees", "enrolled_employees",
        "dependent_count", "average_age", "gender_ratio", "tier_distribution",
        "status",
    ]))
    return out


def claims_json(c):
    out = base(c)
    out.update(_pick(c, [
        "case_id", "experience_period_start", "experience_period_end",
        "months_of_experience", "total_paid_claims_cents",
        "total_enrollment_months", "large_claim_count",
        "pooling_threshold_cents", "pooled_claims_cents",
        "experience_claim_cost_cents", "completion_ratio", "status",
    ]))
    return out


def plan_json(p):
    out = base(p)
    out.update(_pick(p, [
        "case_id", "plan_name", "deductible_individual", "deductible_family",
        "oop_max_individual", "oop_max_family", "coinsurance_pct",
        "copay_primary", "copay_specialist", "actuarial_value",
        "relativity_factor", "employer_contribution_pct",
        "contribution_strategy", "is_reference_plan", "status",
    ]))
    return out


def quote_json(q):
    out = base(q)
    out.update(_pick(q, [
        "case_id", "plan_design_id", "quote_number", "funding_type",
        "pepm_rate_cents", "annual_premium_cents", "renewal_increase_pct",
        "claims_fund_cents", "admin_fee_cents", "stop_loss_premium_cents",
        "broker_commission_cents", "commission_disclosure_required",
        "rate_guarantee_months", "enrollment_change_threshold", "status",
        "negotiation_round", "parent_quote_id",
    ]))
    return out


def stop_loss_json(s):
    out = base(s)
    out.update(_pick(s, [
        "quote_id", "case_id", "specific_deductible_cents",
        "aggregate_attachment_pct", "expected_annual_claims_cents",
        "aggregate_attachment_cents", "specific_premium_cents",
        "aggregate_premium_cents", "total_stop_loss_premium_cents",
        "laser_claimant_ids", "laser_deductible_cents", "status",
    ]))
    return out


def round_json(r):
    out = base(r)
    out.update(_pick(r, [
        "quote_id", "case_id", "round_number", "proposed_by",
        "proposed_pepm_cents", "proposed_contribution_pct",
        "proposed_deductible_individual", "justification", "status",
    ]))
    return out


def enrollment_json(e):
    out = base(e)
    out.update(_pick(e, [
        "case_id", "quote_id", "event_type", "change_count", "effective_date",
        "revised_enrollment", "enrollment_change_pct", "guarantee_voided",
        "rate_adjustment_factor", "status",
    ]))
    return out


def disclosure_json(d):
    out = base(d)
    out.update(_pick(d, [
        "case_id", "quote_id", "broker_id", "total_commission_cents",
        "commission_pct", "per_enrollee_cents", "disclosure_threshold_cents",
        "requires_disclosure", "disclosed_at", "status",
    ]))
    return out
