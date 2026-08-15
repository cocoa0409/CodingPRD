"""Domain thresholds — numeric constants from PRD calculations."""

# Notice obligation: canonical fifty-percent threshold (PRD §3.1/§3.4).
NOTICE_THRESHOLD_DEFAULT = 0.50

# High-cost claimant forecast constants (PRD §3.9).
CREDIBILITY_FULL_MEMBER_COUNT = 500
MANUAL_PER_MEMBER_EXCESS_CENTS = 1_200_000
MANUAL_HIT_RATE = 0.04

# Logical clock startup default (PRD §2.10).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "POLICY_YEAR_START": "2026-01-01T00:00:00Z",
    "POLICY_YEAR_END": "2027-01-01T00:00:00Z",
    "SPECIFIC_DEDUCTIBLE_CENTS": 10_000_000,      # 100000_00
    "AGGREGATE_DEDUCTIBLE_CENTS": 1_000_000_000,  # high enough to stay out of the way
    "FILING_DEADLINE_DAYS": 90,
    "NOTICE_THRESHOLD_PCT": 0.50,
    "RUN_IN_DAYS": 0,
    "RUN_OUT_DAYS": 0,
    "COVERAGE_START": "2025-01-01T00:00:00Z",
    "SERVICE_DATE": "2026-02-01T00:00:00Z",
    "PAID_DATE": "2026-02-02T00:00:00Z",
}
