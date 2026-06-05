"""Serialize stored records to API output shape.

Each entity exposes exactly its scaffold §1.1 fields plus the common fields
(id/created_at/updated_at/version), except PredictabilityLedgerEntry which has
only id+created_at. Internal helper keys (prefixed '_') are stripped.
"""

COMMON = ["id", "created_at", "updated_at", "version"]

ENTITY_FIELDS = {
    "Location": [
        "name", "time_zone", "predictability_pay_enabled", "advance_notice_days",
        "min_rest_hours_between_shifts", "overtime_weekly_threshold_hours",
        "overtime_multiplier", "overtime_cost_guardrail_cents", "status",
    ],
    "Worker": [
        "location_id", "full_name", "email", "is_minor", "minor_daily_cap_hours",
        "minor_weekly_cap_hours", "base_hourly_rate_cents", "no_show_strikes", "status",
    ],
    "Availability": ["worker_id", "kind", "start_utc", "end_utc"],
    "TimeOffRequest": [
        "worker_id", "start_utc", "end_utc", "reason", "status", "decided_by_manager_id",
    ],
    "ShiftTemplate": [
        "location_id", "role_name", "weekday", "local_start_minute",
        "duration_minutes", "forecast_headcount",
    ],
    "Shift": [
        "location_id", "template_id", "role_name", "start_utc", "end_utc",
        "headcount_required", "headcount_filled", "posted_utc", "status", "duration_hours",
    ],
    "Assignment": [
        "shift_id", "worker_id", "pay_period_id", "status", "source",
        "clopening_flag", "provisional_cost_cents", "finalized_cost_cents",
    ],
    "OpenShiftBid": ["shift_id", "worker_id", "seniority_score", "status"],
    "SwapRequest": [
        "from_assignment_id", "to_worker_id", "counter_assignment_id", "status",
        "decided_by_manager_id",
    ],
    "PayPeriod": [
        "location_id", "start_utc", "end_utc", "status",
        "projected_labor_cost_cents", "finalized_labor_cost_cents",
    ],
    "PredictabilityLedgerEntry": [
        "worker_id", "shift_id", "pay_period_id", "reason", "amount_cents",
    ],
}


def view(entity_type, record):
    out = {}
    if entity_type == "PredictabilityLedgerEntry":
        out["id"] = record["id"]
        out["created_at"] = record["created_at"]
        for f in ENTITY_FIELDS[entity_type]:
            out[f] = record.get(f)
        return out
    for f in COMMON:
        out[f] = record.get(f)
    for f in ENTITY_FIELDS[entity_type]:
        out[f] = record.get(f)
    return out
