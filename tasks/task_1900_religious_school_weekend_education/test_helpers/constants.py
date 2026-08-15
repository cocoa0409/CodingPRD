"""Domain thresholds — numeric constants used across test scenarios."""

# The standard year configuration shared by most scenarios.
STANDARD_YEAR = {
    "name": "2026-27",
    "start_date": "2026-09-01",
    "end_date": "2027-06-01",
    "member_tuition_cents": 72500,
    "non_member_tuition_cents": 120000,
    "early_bird_pct": 0.075,
    "early_bird_deadline": "2026-08-15T00:00:00Z",
    "sibling_discount_pcts": [0, 0.10, 0.20],
    "activity_fee_cents": 5000,
    "volunteer_hours_required": 8,
    "volunteer_buyout_fee_cents": 25000,
    "late_fee_pct": 0.015,
    "late_fee_min_balance_cents": 500,
    "tuition_due_date": "2026-10-01",
    "withdrawal_deadline": "2026-09-30",
    "refund_pct_after_deadline": 0.5,
    "attendance_threshold_pct": 80,
}

# Logical-clock constants
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical session dates (Sundays) inside the standard year window.
SESSION_DATES = [
    "2026-09-13",
    "2026-09-20",
    "2026-09-27",
    "2026-10-04",
    "2026-10-11",
    "2026-10-18",
]
