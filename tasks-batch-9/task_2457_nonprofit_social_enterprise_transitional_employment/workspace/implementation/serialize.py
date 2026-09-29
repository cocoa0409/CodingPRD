"""Resource serialisation: datetimes as ISO 8601 UTC with three fractional
digits, Decimals as JSON numbers at their declared precision."""

from datetime import datetime
from decimal import Decimal

from store import fmt_dt

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "business_lines": (
        "name", "market_viability_score", "training_relevance_score", "mission_alignment_score",
        "composite_viability_score", "status", "intake_posture", "training_slots_total",
        "training_slots_filled", "supervisor_capacity", "target_gross_margin_pct",
        "subsidy_cap_cents", "cumulative_subsidy_cents", "quality_incident_count",
        "rejection_reason", "launched_at",
    ),
    "referral_partners": (
        "organization_name", "mou_tier", "mou_status", "referral_quota_per_period",
        "referrals_submitted_count", "enrolled_referral_count", "conversion_rate",
    ),
    "referrals": (
        "referral_partner_id", "candidate_reference", "status", "declared_barrier_codes",
        "verified_barrier_codes", "household_income_cents", "household_size",
        "hours_available_per_week", "fpl_ratio", "eligibility_score", "priority_band",
        "screened_at", "decided_by_user_id",
    ),
    "participants": (
        "referral_id", "business_line_id", "status", "wage_cents_per_hour",
        "max_transitional_weeks", "enrolled_at", "transitional_hours_worked",
        "scheduled_hours_current_week", "support_activity_minutes", "delivered_coaching_count",
        "readiness_certified_by_user_id", "readiness_certified_at", "graduated_at",
        "graduation_wage_cents_per_hour", "re_entry_count", "eligible_re_entry_at",
    ),
    "work_shifts": (
        "business_line_id", "starts_at", "ends_at", "trainee_capacity", "supervisor_user_id",
        "customer_service_standard", "status", "assigned_count", "duration_hours",
        "billable_labor_cost_cents", "quality_defect_count", "customer_complaint_count",
    ),
    "shift_assignments": (
        "work_shift_id", "participant_id", "status", "actual_hours", "quality_defect_count",
        "customer_complaint_count", "wage_cost_cents", "released_reason",
    ),
    "support_activities": (
        "participant_id", "category", "status", "duration_minutes", "cost_cents",
        "delivered_by_user_id", "delivered_at", "voided_reason",
    ),
    "employers": (
        "organization_name", "industry_code", "partnership_status",
        "min_starting_wage_cents_per_hour", "failed_retention_count",
        "confirmed_retention_count", "placement_count", "retention_reliability_pct",
    ),
    "placements": (
        "participant_id", "employer_id", "hire_date", "starting_wage_cents_per_hour",
        "weekly_hours", "employment_status", "wage_verification_status",
        "verified_wage_cents_per_hour", "retention_outcome", "separation_date",
        "separation_days_after_hire", "wage_progression_pct", "at_risk_flag",
    ),
    "retention_checkpoints": (
        "placement_id", "interval_days", "due_date", "status", "still_employed",
        "verified_wage_cents_per_hour", "confirmed_at",
    ),
    "subsidy_periods": (
        "business_line_id", "period_start", "period_end", "status", "supervisor_hours",
        "allocation_basis", "revenue_cents", "trainee_hours", "mission_cost_cents",
        "business_operating_cost_cents", "total_cost_cents", "mission_share",
        "true_cost_per_trainee_hour_cents", "subsidy_per_trainee_hour_cents", "margin_pct",
        "subsidy_rate", "subsidy_draw_cents", "closed_at",
    ),
    "cost_entries": (
        "subsidy_period_id", "source_activity_id", "category", "classification",
        "amount_cents", "status", "allocated_mission_cents", "allocated_business_cents",
        "voided_at",
    ),
}


def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return dict((key, jsonable(item)) for key, item in value.items())
    return value


def dump(record):
    kind = record["_kind"]
    result = {}
    for field in COMMON:
        result[field] = jsonable(record[field])
    for field in FIELDS[kind]:
        result[field] = jsonable(record.get(field))
    if kind == "participants":
        # The window of this metric is pinned to the ISO week containing the
        # logical clock, so it is answered from the clock at read time rather
        # than from whatever week was current when it was last recomputed.
        import derive

        result["scheduled_hours_current_week"] = jsonable(derive.scheduled_week_hours(record))
    return result


def dump_many(records):
    return [dump(record) for record in records]
