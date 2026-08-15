"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Required-nurses floor: every slot demands at least two nurses (PRD 3.2).
MIN_REQUIRED_NURSES = 2

# Charge coverage is required for ADEQUATE when required_nurses >= 2 (PRD 3.3).
CHARGE_MIN_REQUIRED = 2

# Overtime regime (PRD 2.9 / 3.4 / 3.8).
OT_WEEKLY_THRESHOLD_HOURS = 40
OT_MULTIPLIER = 1.5

# Missed-break penalty per break, in cents (PRD 3.8).
MISSED_BREAK_PENALTY_CENTS = 5000

# Reference hourly rate for the offer budget reserve (PRD 3.6).
REFERENCE_RATE_CENTS = 6000

# Float selector weekly projected-hours ceiling (PRD 3.5).
MAX_WEEK_PROJECTED_HOURS = 60

# Every assignment carries 12 scheduled hours regardless of code (PRD 2.9).
SCHEDULED_HOURS = 12.0

# Standard staffing matrix ratios used across scenarios.
ICU_RATIOS = {"LOW": 4, "MODERATE": 3, "HIGH": 2, "CRITICAL": 1}
MED_SURG_RATIOS = {"LOW": 5, "MODERATE": 4, "HIGH": 2, "CRITICAL": 1}

# Scenario dates (2026-08-10 is the Monday of ISO week 33).
MONDAY = "2026-08-10"
TUESDAY = "2026-08-11"
WEDNESDAY = "2026-08-12"
THURSDAY = "2026-08-13"
WEEK_START_MONDAY = "2026-08-10"

TEST_DEFAULTS = {
    "INCENTIVE_BUDGET_CENTS": 500000,
    "BASE_HOURLY_RATE_CENTS": 5000,
}
