"""Domain thresholds — numeric constants from the PRD calculations and §3 narratives."""

# Class multipliers used by the premium-rate calculation (PRD §3.4).
CLASS_MULT = {
    "STANDARD": 1.00,
    "TOBACCO": 1.50,
    "SUBSTANDARD": 2.00,
}

# Days-per-year divisor used by interest accrual and graded-refund interest (PRD §3.9, §3.12).
DAYS_PER_YEAR = 365

# Canonical GRADED plan defaults reused across fixtures (the PRD's documented defaults).
PLAN_DEFAULTS = {
    "base_monthly_rate_per_1000_cents": 400,
    "graded_period_months": 24,
    "contestability_period_months": 24,
    "graded_refund_apr": 0.10,
    "cash_value_factor_per_1000_cents": 1500,
    "cash_value_vesting_years": 3,
    "max_loan_to_cash_value_pct": 0.90,
    "loan_apr": 0.08,
    "loan_cooldown_days": 30,
    "grace_period_days": 31,
    "reinstatement_window_days": 180,
    "min_issue_age": 45,
    "max_issue_age": 85,
}

# Clock default before any set (PRD §2.4).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# A standard issue clock used across fixtures.
DEFAULT_ISSUE_CLOCK = "2026-02-01T00:00:00Z"
