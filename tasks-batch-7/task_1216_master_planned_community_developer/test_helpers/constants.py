"""Domain thresholds — numeric constants from the PRD calculation narratives."""

# Fixed logical epoch: before any clock call the server reads this instant.
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
DEFAULT_CLOCK_MILLIS = "2026-05-01T00:00:00.000Z"

THRESHOLDS = {
    # Governance posture percentages (PRD transition-stage section)
    "OWNER_REPRESENTATION_PCT": 25.00,
    "PARITY_PCT": 50.00,
    "OWNER_MAJORITY_PCT": 75.00,
    "TURNOVER_PCT": 100.00,
    # Board
    "TOTAL_SEATS": 5,
    "QUORUM_PCT": 20,
    "ELECTION_WINDOW_DAYS": 30,
    # Takedown tranches
    "TRANCHE_OPEN_LEAD_DAYS": 30,
    "CURE_PERIOD_DAYS": 14,
    "PENALTY_CAP_PCT": 25,
    # Closings
    "RESCISSION_WINDOW_DAYS": 30,
    # Assessments
    "STATUTORY_CAP_PCT": 20.00,
    "ASSESSMENT_NOTICE_LEAD_DAYS": 30,
    "BUDGET_NOTICE_LEAD_DAYS": 14,
    # Design review
    "MAX_REVIEW_ROUNDS": 3,
    "REVIEW_ROUND_FEE_R2": 25000,
    "REVIEW_ROUND_FEE_R3": 75000,
    "CONSTRUCTION_START_WINDOW_DAYS": 180,
    # Violations
    "VIOLATION_CURE_DAYS": 14,
    "APPEAL_WINDOW_DAYS": 30,
    "FINE_TIER1_DAILY_CENTS": 5000,
    "FINE_TIER2_DAILY_CENTS": 10000,
    "FINE_TIER3_DAILY_CENTS": 20000,
    "FINE_CAP_CENTS": 1000000,
    # Events / sales center
    "EVENT_LEAD_DAYS": 14,
    "MAX_CONCURRENT_TOURS": 3,
}

TEST_DEFAULTS = {
    "BASE_PRICE_PER_LOT_CENTS": 5000000,
    "ANNUAL_ESCALATION_PCT": 6.0,
    "PENALTY_PER_LOT_PER_DAY_CENTS": 1000,
    "EARNEST_MONEY_CENTS": 1000000,
    "INTEREST_RATE_ANNUAL_PCT": 5.0,
    "DIRECTOR_NAMES": ["D1", "D2", "D3", "D4", "D5"],
}
