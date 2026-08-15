"""Domain thresholds and rates — numeric constants named in the PRD."""

# FICA coverage: cumulative cash wages at or above this amount trigger coverage (PRD §3.8).
FICA_COVERAGE_THRESHOLD_CENTS = 280000

# Social Security wage base and rates (PRD §3.6).
SS_WAGE_BASE_CENTS = 17610000
SS_RATE = 0.062
MEDICARE_RATE = 0.0145
ADDL_MEDICARE_RATE = 0.009
ADDL_MEDICARE_THRESHOLD_CENTS = 20000000

# FUTA quarterly trigger and annual wage base (PRD §3.8).
FUTA_QUARTER_TRIGGER_CENTS = 100000
FUTA_WAGE_BASE_CENTS = 700000
FUTA_RATE = 0.006

# Paid leave accrual (PRD §3.7).
LEAVE_ACCRUAL_DIVISOR = 30
LEAVE_ANNUAL_CAP_MINUTES = 2400

# Safe-harbor deposit requirement (PRD §3.9).
ESTIMATED_PAYMENT_THRESHOLD_CENTS = 100000
SAFE_HARBOR_PRIOR_YEAR_PCT = 1.10
UNDERPAYMENT_ACTUAL_PCT = 0.90

# Period arithmetic (PRD §3.6 / §3.9).
WEEKS_PER_PERIOD = {"WEEKLY": 1, "BIWEEKLY": 2, "SEMIMONTHLY": 2, "MONTHLY": 4}
PERIODS_PER_YEAR = {"WEEKLY": 52, "BIWEEKLY": 26, "SEMIMONTHLY": 24, "MONTHLY": 12}

# Logical clock default before any client sets it (PRD §2.5).
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 3000,   # 50 cents per minute
    "RATE_PER_MINUTE_CENTS": 50,
    "GUARANTEE_MINUTES_PER_WEEK": 2400,
    "WEEKLY_OT_THRESHOLD_MINUTES": 2400,
}
