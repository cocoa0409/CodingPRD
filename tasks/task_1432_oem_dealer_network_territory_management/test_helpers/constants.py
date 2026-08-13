"""Domain thresholds — numeric constants named by the PRD (section 3)."""

THRESHOLDS = {
    # Tier discount (PRD 3.3): ratio thresholds and rates.
    "TIER_GOLD_THRESHOLD": 1.2,
    "TIER_SILVER_THRESHOLD": 1.0,
    "RATE_GOLD": 0.08,
    "RATE_SILVER": 0.05,
    "RATE_BRONZE": 0.02,
    # Scorecard (PRD 3.8).
    "REQUIRED_ACTIVE_CERTS": 2,
    "TERMINATION_SCORE_THRESHOLD": 60,
    # Chargeback auto-suspension (PRD 3.5 / 3.8).
    "CHARGEBACK_SUSPENSION_CENTS": 50000,
    # Floor-plan aging (PRD 3.4).
    "FREE_DAYS": 90,
    "PAST_DUE_DAYS": 90,
    "DEFAULT_DAYS": 270,
    "DAILY_RATE_1": 0.0002,
    "DAILY_RATE_2": 0.0004,
    "DAILY_RATE_3": 0.0006,
    # Parts returns (PRD 3.6).
    "RESTOCK_PCT": 0.15,
    "RETURN_ALLOWANCE_PCT": 0.05,
    # Warranty labor rates in cents per hour (PRD 3.5).
    "LABOR_RATE_GOLD": 12000,
    "LABOR_RATE_SILVER": 10000,
    "LABOR_RATE_BRONZE": 8500,
    # Lead SLA (PRD 3.7).
    "LEAD_SLA_HOURS": 72,
}

TEST_DEFAULTS = {
    # Logical clock startup default (PRD 2.6).
    "CLOCK_START": "2026-08-01T00:00:00Z",
    "CREDIT_LIMIT_CENTS": 500000,
    "AGREEMENT_EFFECTIVE": "2026-01-01",
    "AGREEMENT_EXPIRY": "2026-12-31",
    "ASSIGNMENT_STARTS": "2026-01-01",
    "ASSIGNMENT_ENDS": "2026-12-31",
    "CERT_EARNED": "2026-01-10",
    "CERT_EXPIRES": "2028-01-10",
    "QUARTER_YEAR": 2026,
    "QUARTER": 3,
}
