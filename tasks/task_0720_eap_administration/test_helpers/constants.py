"""Domain thresholds — numeric constants from PRD calculations."""

# Out-of-network reimbursement reduction factor (70%, floor applied)
OON_FACTOR_NUM = 7
OON_FACTOR_DEN = 10

# Default contract / plan literals used across difficulty + corner fixtures.
TEST_DEFAULTS = {
    "SESSIONS_PER_ISSUE": 2,
    "ANNUAL_SESSION_CAP": 10,
    "SESSION_RATE_CENTS": 12000,
    "CRISIS_SLA_MINUTES": 15,
    "REPORTING_MIN_COHORT": 2,
    "ANNUAL_REIMBURSEMENT_BUDGET_CENTS": 1_000_000,
    "COPAY_CENTS": 2000,
    "WORKLIFE_REFERRALS_PER_YEAR": 3,
    "DURATION_MINUTES": 50,
}

# Server logical clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Field defaults declared in the PRD.
DEFAULT_CRISIS_SLA_MINUTES = 15
DEFAULT_REPORTING_MIN_COHORT = 5
DEFAULT_WORKLIFE_REFERRALS_PER_YEAR = 3
DEFAULT_COPAY_CENTS = 0
DEFAULT_DURATION_MINUTES = 50
