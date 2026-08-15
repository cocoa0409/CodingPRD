"""Domain thresholds — numeric constants from PRD calculations (§2.9, §3)."""

# goal_status_rule (PRD §3.4): pct thresholds, 0.70 inclusive
GOAL_TIER_MET = 1.00
GOAL_TIER_ON_TRACK = 0.70
GOAL_TIER_AT_RISK = 0.40

# pip_attainment_ratio (PRD §3.6): SUCCESS outcome guard
ATTAINMENT_SUCCESS_THRESHOLD = 0.80

# legal_risk_score weights (PRD §3.5)
LEGAL_RISK_WEIGHTS = {
    "PROTECTED_CLASS": 20,
    "RECENT_LEAVE": 15,
    "WHISTLEBLOWER_HISTORY": 30,
    "PRIOR_COMPLAINT": 10,
    "RETALIATION_WINDOW": 25,
    "DOCUMENTATION_GAP": 0,
}
LEGAL_DOC_GAP_MULTIPLIER = 2
LEGAL_COMPOUND_THRESHOLD = 50
LEGAL_COMPOUND_BONUS = 10
LEGAL_RISK_MAX = 100

# Rebuttal window (PRD §3.7): decided_at + 5 days, inclusive
REBUTTAL_WINDOW_DAYS = 5

# Consistency review cohort minimum (PRD §3.8)
COHORT_MIN_SIZE = 3

# Check-in sweep (PRD §3.4): unheld > 3 days past scheduled_for -> MISSED
CHECKIN_MISSED_AFTER_DAYS = 3

# Rating cycle archival guard (PRD §3.1): window_end + 365 days
CYCLE_ARCHIVE_AFTER_DAYS = 365

# Logical clock initial reading (PRD §2.5)
CLOCK_INITIAL = "2026-08-01T00:00:00Z"
