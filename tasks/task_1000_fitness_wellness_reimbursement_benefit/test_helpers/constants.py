"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    "ELIGIBILITY_WAIT_DAYS": 30,
    "FRAUD_FLAG_THRESHOLD": 50,
    "FRAUD_BLOCK_THRESHOLD": 80,
    "VELOCITY_WINDOW_DAYS": 7,
    "VELOCITY_FREE_COUNT": 5,
    "MAX_RESUBMISSIONS": 3,
    "DEPENDENT_CAP_MAX": 3,
    "FILING_DEADLINE_DAYS": 90,
    "CHILD_AGE_LIMIT": 26,
    "VISIT_FREQUENCY_WINDOW_DAYS": 30,
}

# Standard INDIVIDUAL tier used by most fixtures:
# annual 30000 / quarterly 10000 / per-claim 5000 / freq cap 8.
STANDARD_TIER = {
    "tier_code": "INDIVIDUAL",
    "annual_allowance_cents": 30000,
    "quarterly_cap_cents": 10000,
    "per_claim_cap_cents": 5000,
    "visit_frequency_cap": 8,
    "dependent_cap_pct": 0.25,
    "in_network_pct": 1.0,
    "preferred_pct": 0.8,
    "out_of_network_pct": 0.5,
}

TEST_DEFAULTS = {
    "PLAN_PERIOD_START": "2026-01-01T00:00:00Z",
    "PLAN_PERIOD_END": "2026-12-31T23:59:59Z",
    "BENEFIT_YEAR": 2026,
    "FUNDING_OPENING_CENTS": 100000,
    "PROVIDER_CONTRACT_START": "2026-01-01T00:00:00Z",
    "PROVIDER_CONTRACT_END": "2026-12-31T23:59:59Z",
    "VISIT_RATE_CENTS": 1500,
    "MEMBER_HIRE_DATE": "2026-03-01T00:00:00Z",
    # Default logical clock at server startup (PRD §2.5).
    "DEFAULT_CLOCK": "2026-05-01T00:00:00Z",
}
