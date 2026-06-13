"""Domain thresholds — numeric constants from the PRD's calculations."""

# Screening thresholds (PRD §3.2)
SCREENING = {
    "MIN_CREDIT": 620,        # credit score is an at-least test (>=)
    "MAX_RTI": 0.40,          # rent-to-income is an at-most test (<=)
    "MAX_DTI": 0.45,          # debt-to-income is an at-most test (<=)
    "ZERO_INCOME_SENTINEL": 999.9999,
}

# Deposit interest (PRD §3.6)
STATE_INTEREST_RATE = {
    "CA": 0.0000,
    "NY": 0.0150,
    "IL": 0.0050,
    "FL": 0.0000,
    "TX": 0.0000,
}
DAYS_PER_YEAR = 365

# Eviction cure windows by state and reason (PRD §3.8), in whole days.
STATE_CURE_DAYS = {
    "CA": {"NONPAYMENT": 3, "LEASE_VIOLATION": 3, "HOLDOVER": 30},
    "NY": {"NONPAYMENT": 14, "LEASE_VIOLATION": 10, "HOLDOVER": 30},
    "TX": {"NONPAYMENT": 3, "LEASE_VIOLATION": 3, "HOLDOVER": 3},
    "IL": {"NONPAYMENT": 5, "LEASE_VIOLATION": 10, "HOLDOVER": 30},
    "FL": {"NONPAYMENT": 3, "LEASE_VIOLATION": 7, "HOLDOVER": 15},
}

# Turnover default turnaround applied by the eviction-enforce cascade (PRD §3.8).
DEFAULT_TURN_DAYS = 14

# Waterfall ordering ranks (PRD §3.5).
LATE_FEE_RANK = 0
RENT_RANK = 1

# Common test defaults.
TEST_DEFAULTS = {
    "MANAGEMENT_FEE_PCT": 0.08,
    "MARKET_RENT_CENTS": 200000,
    "MONTHLY_RENT_CENTS": 200000,
    "ANNUAL_INCOME_CENTS": 12000000,
    "CREDIT_SCORE": 700,
    "REQUESTED_RENT_CENTS": 200000,
}
