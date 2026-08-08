"""Domain thresholds — numeric constants from PRD calculations (§2, §3)."""

# Eligibility score components (§3.2)
THRESHOLDS = {
    "JOBS_WEIGHT": 30,
    "INVESTMENT_WEIGHT": 30,
    "BUT_FOR_BONUS": 25,
    "DISTRESS_BONUS": 15,
    "MET_THRESHOLD_PCT": 100.00,
    "DEFAULT_BUT_FOR_PASS_THRESHOLD": 60,
    "DEFAULT_DISCLOSURE_THRESHOLD_CENTS": 0,
}

# Common test values used across fixtures.
TEST_DEFAULTS = {
    "GRANT_PER_JOB_CENTS": 500_000,
    "MIN_JOBS_REQUIRED": 50,
    "MIN_INVESTMENT_CENTS": 100_000_000,
    "PROGRAM_BUDGET_CENTS": 1_000_000_000,
    "MAX_TERM_YEARS": 10,
}

# A UUID that is well-formed but never minted by the server.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
