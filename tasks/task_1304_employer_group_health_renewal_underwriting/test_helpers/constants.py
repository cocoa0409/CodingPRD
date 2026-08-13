"""Domain thresholds — numeric constants from PRD calculation rules."""

THRESHOLDS = {
    # Credibility
    "MIN_GROUP_SIZE": 25,
    "FULL_CREDIBILITY_SIZE": 500,
    "MIN_EXPERIENCE_MONTHS": 12,
    "FULL_EXPERIENCE_MONTHS": 24,
    # Manual rating
    "BASE_MANUAL_RATE_CENTS": 45000,
    # Experience rating
    "ANNUAL_TREND": 0.065,
    "RETENTION_PCT": 0.15,
    # Blended rating
    "DEFAULT_RATE_CAP_PCT": 0.15,
    # Level-funded split
    "CLAIMS_FUND_SHARE": 0.82,
    "ADMIN_FEE_SHARE": 0.12,
    "STOP_LOSS_SHARE": 0.06,
    # Commission disclosure: $50 per enrollee per year in cents
    "DISCLOSURE_THRESHOLD_PER_ENROLLEE_CENTS": 5000,
    # Stop-loss pricing
    "AGGREGATE_RATE": 0.02,
    "LASER_LOAD_PCT": 0.25,
    # Quote expiry: 30 days before effective date
    "QUOTE_EXPIRY_DAYS_BEFORE_EFFECTIVE": 30,
    # Level-funded minimum group size
    "MIN_GROUP_SIZE_LEVEL_FUNDED": 10,
}

TEST_DEFAULTS = {
    "GROUP_SIZE": 500,
    "ENROLLED": 400,
    "CURRENT_PREMIUM_ANNUAL": 24000000,
    "EXPECTED_EXPERIENCE_RATE_24MO": 5338,
    "EXPECTED_ANNUAL_PREMIUM_REFERENCE": 25622400,
}
