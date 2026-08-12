"""Domain thresholds and constants from the PRD's calculation rules."""

# Logical clock startup value (PRD: the logical clock starts at exactly
# 2026-05-01T00:00:00Z; the wall clock is never read).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Per-modality base RVU values (study_rvu rule).
RVU_BASE = {
    "CT": 1.5,
    "MR": 2.0,
    "XR": 0.5,
    "US": 1.0,
    "NM": 1.5,
    "MG": 1.0,
}

# Report credit factors (report_rvu_credit rule).
PRELIM_FACTOR = 0.8
DISCREPANCY_PENALTY = {0: 0.0, 1: 0.0, 2: 0.25, 3: 0.5}

# Volume pricing tiers (invoice_volume_pricing rule).
TIER1_LIMIT = 1000
TIER1_RATE_CENTS = 901
TIER2_LIMIT = 5000
TIER2_RATE_CENTS = 801
TIER3_RATE_CENTS = 701
AFTER_HOURS_MULTIPLIER = 1.5
CRITICAL_ADDON_CENTS = 250

# Per-unit after-hours pinned rounding: round_half_up(901 * 1.5) == 1352.
AFTER_HOURS_TIER1_UNIT_CENTS = 1352

# Hospital default configuration.
DEFAULT_TAT_STAT_MINUTES = 60
DEFAULT_TAT_URGENT_MINUTES = 240
DEFAULT_TAT_ROUTINE_MINUTES = 1440
DEFAULT_PENALTY_PER_BREACH_MINUTE_CENTS = 50
DEFAULT_BREACH_PENALTY_CAP_CENTS = 20000
DEFAULT_FATIGUE_CAP_RVU = 30.0
DEFAULT_MAX_CONCURRENT_STAT = 3

# Fatigue accounting window (fatigue_utilization rule).
FATIGUE_WINDOW_HOURS = 24

# Critical-result auto-escalation thresholds (communication workflow).
NOTICE_PENDING_ESCALATE_MINUTES = 30
NOTICE_NOTIFIED_ESCALATE_MINUTES = 60

# Billing-period reopen grace, in inclusive days after period_end.
REOPEN_GRACE_DAYS = 7

# Well-formed UUID that never resolves to a persisted row.
NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"
