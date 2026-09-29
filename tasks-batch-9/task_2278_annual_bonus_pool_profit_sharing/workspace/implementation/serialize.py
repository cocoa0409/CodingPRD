"""Entity -> JSON projections.

Field sets follow SCAFFOLD.yaml `entities` exactly.  Decimal values (percentages,
multipliers, ratios) are emitted as JSON numbers; money is always integer cents.
`EligibilityEvent` carries only `id` and `created_at` from the common field set
(PRD 2.4).
"""

from decimal import Decimal

PLAN_FIELDS = [
    "id", "plan_year", "plan_name", "plan_period_start", "plan_period_end",
    "payment_date", "company_weight_pct", "business_unit_weight_pct",
    "individual_weight_pct", "discretionary_budget_pct",
    "termination_treatment_policy", "status", "company_achievement_pct",
    "bu_weighted_achievement_pct", "blended_achievement_pct",
    "funding_multiplier", "total_target_cents", "funded_pool_cents",
    "aggregate_rounding_delta_cents", "discretionary_budget_cents",
    "discretionary_used_cents", "accrued_base_cents", "accrued_total_cents",
    "locked_total_cents", "paid_total_cents", "forfeited_total_cents",
    "dispute_adjustment_cents", "settlement_burden_cents", "true_up_cents",
    "over_allocated_pool_count", "under_utilized_pool_count",
    "governance_posture", "certified_by_user_id", "locked_by_user_id",
    "created_at", "updated_at", "version",
]

METRIC_FIELDS = [
    "id", "plan_id", "metric_code", "weight_pct", "threshold_value",
    "target_value", "max_value", "actual_value", "source_note",
    "achievement_pct", "status", "created_at", "updated_at", "version",
]

BUSINESS_UNIT_FIELDS = [
    "id", "unit_code", "name", "created_at", "updated_at", "version",
]

JOB_LEVEL_TARGET_FIELDS = [
    "id", "plan_id", "job_level", "target_bonus_pct", "guideline_min_ratio",
    "guideline_max_ratio", "created_at", "updated_at", "version",
]

PARTICIPANT_FIELDS = [
    "id", "plan_id", "business_unit_id", "employee_code", "full_name",
    "job_level", "base_salary_cents", "hire_date", "employment_status",
    "termination_date", "termination_reason", "current_job_level",
    "current_base_salary_cents", "current_business_unit_id",
    "created_at", "updated_at", "version",
]

EVENT_FIELDS = [
    "id", "participant_id", "event_type", "effective_date", "new_job_level",
    "new_base_salary_cents", "new_business_unit_id", "leave_end_date",
    "paid_leave", "termination_reason", "supersedes_event_id", "superseded",
    "note", "created_at",
]

POOL_FIELDS = [
    "id", "plan_id", "business_unit_id", "bu_metric_achievement_pct",
    "scorecard_narrative", "calibration_status", "eligible_target_cents",
    "eligible_headcount", "funded_cents", "allocated_cents",
    "available_cents", "min_utilization_cents", "utilization_pct",
    "top_tier_award_count", "max_top_tier_count", "distribution_status",
    "calibration_returned_count", "scorecard_certified_by_user_id",
    "created_at", "updated_at", "version",
]

AWARD_FIELDS = [
    "id", "plan_id", "participant_id", "business_unit_id", "bu_pool_id",
    "target_bonus_pct", "credited_days", "excluded_leave_days",
    "segment_count", "prorated_target_cents", "eligibility_status",
    "allocation_status", "payment_status", "proposed_allocation_cents",
    "allocation_ratio", "adjustment_total_cents", "final_award_cents",
    "payout_amount_cents", "allocation_rationale", "retraction_count",
    "created_at", "updated_at", "version",
]

ADJUSTMENT_FIELDS = [
    "id", "plan_id", "award_id", "adjustment_cents", "justification",
    "documentation_ref", "per_award_cap_cents", "status",
    "submitted_by_user_id", "decided_by_user_id", "decision_note",
    "created_at", "updated_at", "version",
]

ACCRUAL_FIELDS = [
    "id", "plan_id", "period_start", "period_end",
    "forecast_company_achievement_pct", "status", "provisional_target_basis",
    "provisional_pool_cents", "elapsed_days", "cumulative_accrual_target_cents",
    "period_accrual_cents", "burden_rate_pct", "burden_cents",
    "total_period_cents", "posting_note", "reversal_reason",
    "created_at", "updated_at", "version",
]

PAYOUT_RUN_FIELDS = [
    "id", "plan_id", "run_note", "status", "payment_date_used",
    "paid_award_count", "deferred_award_count", "forfeited_award_count",
    "total_paid_cents", "total_forfeited_cents", "settlement_burden_cents",
    "true_up_cents", "settlement_note", "created_at", "updated_at", "version",
]

DISPUTE_FIELDS = [
    "id", "plan_id", "award_id", "participant_id", "dispute_reason",
    "claimed_amount_cents", "status", "reviewer_note", "resolution",
    "adjusted_amount_cents", "resolution_note", "assigned_by_user_id",
    "resolved_by_user_id", "created_at", "updated_at", "version",
]


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _project(rec, fields):
    return {name: _jsonable(rec.get(name)) for name in fields}


def plan_out(rec):
    return _project(rec, PLAN_FIELDS)


def metric_out(rec):
    return _project(rec, METRIC_FIELDS)


def business_unit_out(rec):
    return _project(rec, BUSINESS_UNIT_FIELDS)


def job_level_target_out(rec):
    return _project(rec, JOB_LEVEL_TARGET_FIELDS)


def participant_out(rec):
    return _project(rec, PARTICIPANT_FIELDS)


def event_out(rec):
    return _project(rec, EVENT_FIELDS)


def pool_out(rec):
    return _project(rec, POOL_FIELDS)


def award_out(rec):
    return _project(rec, AWARD_FIELDS)


def adjustment_out(rec):
    return _project(rec, ADJUSTMENT_FIELDS)


def accrual_out(rec):
    return _project(rec, ACCRUAL_FIELDS)


def payout_run_out(rec):
    return _project(rec, PAYOUT_RUN_FIELDS)


def dispute_out(rec):
    return _project(rec, DISPUTE_FIELDS)
