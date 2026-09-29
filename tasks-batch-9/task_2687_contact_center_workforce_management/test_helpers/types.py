"""Shared type aliases and field inventories for the fifteen entity types.

The field inventories below are the field names the PRD declares for each
entity, and they are what the shape assertions in ``assertions.py`` walk.  They
are deliberately data, not code: a test asserting "every declared field comes
back" reads the inventory rather than restating forty names inline.
"""

from typing import Any, Dict, List

Json = Dict[str, Any]
Headers = Dict[str, str]
JsonList = List[Json]

# Every entity carries these four.
COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]

PLANNING_CYCLE_FIELDS = COMMON_FIELDS + [
    "name",
    "horizon_start_date",
    "horizon_end_date",
    "interval_minutes",
    "requirement_basis",
    "ot_budget_cents",
    "intraday_alert_short_threshold",
    "posture",
    "reforecast_generation",
    "short_interval_count",
    "total_scheduled_hours",
    "ot_spend_committed_cents",
    "ot_hours_committed",
    "headcount_active",
    "pipeline_fte",
    "requirements_locked_at",
    "published_at",
]

LABOR_AGREEMENT_FIELDS = COMMON_FIELDS + [
    "code",
    "min_rest_hours",
    "max_weekly_hours",
    "max_consecutive_days",
    "vto_min_notice_hours",
    "preference_honor_floor_pct",
    "ot_premium_multiplier",
    "enrolled_agent_count",
]

FORECAST_GROUP_FIELDS = COMMON_FIELDS + [
    "planning_cycle_id",
    "channel",
    "skill_code",
    "base_daily_volume",
    "base_aht_seconds",
    "operating_start_minute",
    "operating_end_minute",
    "intraday_curve",
    "dow_multipliers",
    "service_level_target_pct",
    "service_level_seconds",
    "occupancy_target_pct",
    "shrinkage_pct",
    "reforecast_multiplier",
    "interval_count",
]

MARKETING_EVENT_FIELDS = COMMON_FIELDS + [
    "planning_cycle_id",
    "name",
    "uplift_pct",
    "confidence_tier",
    "window_start",
    "window_end",
    "forecast_group_id",
    "channel_scope",
    "supersedes_event_id",
    "status",
    "weighted_uplift_pct",
]

INTERVAL_PLAN_FIELDS = COMMON_FIELDS + [
    "forecast_group_id",
    "service_date",
    "interval_index",
    "interval_start",
    "interval_end",
    "volume_forecast",
    "aht_forecast_seconds",
    "applied_event_uplift_pct",
    "required_service_level",
    "required_occupancy_capped",
    "required_agents",
    "scheduled_agents",
    "routing_inflow_agents",
    "routing_outflow_agents",
    "effective_scheduled_agents",
    "coverage_gap",
    "coverage_state",
    "internal_capacity_volume",
    "allocatable_volume",
    "partner_committed_volume",
    "unserved_volume",
    "actual_volume",
    "actual_aht_seconds",
    "observed_ratio",
    "smoothed_ratio",
]

AGENT_FIELDS = COMMON_FIELDS + [
    "labor_agreement_id",
    "employee_code",
    "full_name",
    "skills",
    "seniority_rank",
    "weekly_contracted_hours",
    "hourly_rate_cents",
    "status",
    "hiring_class_id",
    "scheduled_hours_committed",
    "adherence_pct",
    "coaching_flag_count",
    "coaching_status",
]

SHIFT_TEMPLATE_FIELDS = COMMON_FIELDS + [
    "planning_cycle_id",
    "code",
    "skill_code",
    "start_time_local",
    "duration_minutes",
    "unpaid_break_minutes",
    "days_of_week",
    "slots_total",
    "slots_awarded",
]

BID_ROUND_FIELDS = COMMON_FIELDS + [
    "planning_cycle_id",
    "code",
    "max_reopen_count",
    "status",
    "reopen_count",
    "awarded_bid_count",
    "unfilled_bid_count",
    "preference_honor_rate",
]

SHIFT_BID_FIELDS = COMMON_FIELDS + [
    "bid_round_id",
    "agent_id",
    "preference_template_ids",
    "status",
    "awarded_shift_template_id",
    "awarded_preference_index",
]

SCHEDULE_SHIFT_FIELDS = COMMON_FIELDS + [
    "planning_cycle_id",
    "agent_id",
    "shift_template_id",
    "service_date",
    "start_at",
    "end_at",
    "unpaid_break_seconds",
    "scheduled_seconds",
    "paid_hours",
    "ot_hours",
    "vto_hours",
    "publication_status",
    "adherence_status",
    "out_of_adherence_seconds",
    "excused_seconds",
    "adherence_pct",
    "flagged_by_user_id",
]

ADHERENCE_EXCEPTION_FIELDS = COMMON_FIELDS + [
    "schedule_shift_id",
    "agent_id",
    "reason_code",
    "duration_seconds",
    "narrative",
    "status",
    "info_requested_count",
    "coach_note",
    "decided_by_user_id",
]

INTRADAY_ACTION_FIELDS = COMMON_FIELDS + [
    "planning_cycle_id",
    "kind",
    "expires_at",
    "agent_id",
    "schedule_shift_id",
    "target_forecast_group_id",
    "source_forecast_group_id",
    "hours",
    "agents_shifted",
    "interval_start",
    "status",
    "cost_cents",
    "ot_multiplier_applied",
    "responded_by_user_id",
]

OUTSOURCE_PARTNER_FIELDS = COMMON_FIELDS + [
    "legal_name",
    "skill_codes",
    "rate_per_contact_millicents",
    "interval_max_volume",
    "commitment_floor_volume",
    "performance_threshold_pct",
    "billing_basis",
    "status",
    "performance_report_count",
    "latest_sl_attainment_pcts",
    "rolling_sl_attainment_pct",
    "consecutive_breach_count",
    "committed_volume_outstanding",
    "invoice_total_cents",
]

PARTNER_ALLOCATION_FIELDS = COMMON_FIELDS + [
    "outsource_partner_id",
    "interval_plan_id",
    "allocated_volume",
    "status",
    "proposed_by_user_id",
    "committed_by_user_id",
    "delivered_volume",
    "settlement_floor_cents",
    "settlement_delivered_cents",
    "shortfall_penalty_cents",
    "settlement_amount_cents",
]

HIRING_CLASS_FIELDS = COMMON_FIELDS + [
    "planning_cycle_id",
    "labor_agreement_id",
    "cohort_name",
    "skill_code",
    "start_date",
    "seats",
    "training_weeks",
    "nesting_weeks",
    "expected_attrition_pct",
    "graduate_hourly_rate_cents",
    "graduate_weekly_hours",
    "status",
    "expected_graduates",
    "nesting_from_date",
    "productive_from_date",
    "effective_fte_at_horizon_end",
    "graduated_agent_count",
]

# The cycle-wide coverage rollup is a derived view: it carries neither an id
# nor any of the other bookkeeping fields.
COVERAGE_SUMMARY_FIELDS = [
    "planning_cycle_id",
    "posture",
    "interval_count",
    "short_interval_count",
    "total_required_agents",
    "total_effective_scheduled_agents",
    "total_coverage_gap",
    "total_allocatable_volume",
    "total_partner_committed_volume",
    "total_unserved_volume",
]
