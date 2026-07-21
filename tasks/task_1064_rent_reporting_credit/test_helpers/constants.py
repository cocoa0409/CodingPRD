"""Domain thresholds — numeric constants from the PRD (§2.4, §2.6, §3.4, §3.6, §3.7)."""

# Payment on-time grace period, in whole days (PRD §3.4).
GRACE_DAYS = 5

# Back-report fee model (PRD §3.6).
BACK_REPORT_PER_MONTH_CENTS = 200
BACK_REPORT_FEE_CAP_CENTS = 3000
BACK_REPORT_MAX_MONTHS = 24

# Dispute windows, in whole days (PRD §3.7). The PRD fixes both at thirty days.
DISPUTE_WINDOW_DAYS = 30
DISPUTE_INVESTIGATION_DAYS = 30

# Logical-clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"

# Score bounds (PRD §3.1).
SCORE_MIN = 300
SCORE_MAX = 850

# Convenience test defaults.
TEST_DEFAULTS = {
    "MONTHLY_FEE_CENTS": 1499,
    "RENT_AMOUNT_CENTS": 120000,
    "BACK_REPORTING_INCLUDED_MONTHS": 6,
}
