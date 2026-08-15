"""Domain thresholds — numeric constants from PRD rules."""

# Statutory windows / rates
THRESHOLDS = {
    # 20% lump-sum withholding and the 20000-cent ($200.00) gross floor
    "WITHHOLDING_RATE_NUM": 20,
    "WITHHOLDING_RATE_DEN": 100,
    "WITHHOLDING_FLOOR_CENTS": 20000,
    # Default-treatment tiers
    "CASHOUT_LIMIT_CENTS": 100000,
    "FORCED_ROLLOVER_LIMIT_CENTS": 500000,
    # Earnings-adjusted restoration
    "ADJUSTMENT_RATE_NUM": 45,
    "ADJUSTMENT_RATE_DEN": 1000,
    "ADJUSTMENT_YEAR_DAYS": 365,
    # Statutory day windows
    "NOIT_MIN_DAYS": 60,
    "NOIT_MAX_DAYS": 90,
    "INTERESTED_PARTY_MIN_DAYS": 10,
    "INTERESTED_PARTY_MAX_DAYS": 24,
    "BLACKOUT_ADVISORY_MIN_DAYS": 30,
    "BLACKOUT_ADVISORY_MAX_DAYS": 60,
    "CERTIFIED_MAIL_BUFFER_DAYS": 15,
    "STALE_CHECK_DAYS": 90,
    "DEFAULT_TREATMENT_LAG_DAYS": 30,
    # Fiduciary narrative minimum length
    "NARRATIVE_MIN_CHARS": 50,
}

# Pinned timeline (PRD's logical clock startup value and shared test anchors)
DATES = {
    "CLOCK_STARTUP_DEFAULT": "2026-08-01T00:00:00Z",
    "PROPOSED_TERMINATION_DATE": "2026-10-15T00:00:00Z",
    "DISTRIBUTION_EFFECTIVE_DATE": "2026-10-20T00:00:00Z",
    "DEFAULT_TREATMENT_DATE": "2026-11-19T00:00:00Z",
    "AFTER_DEFAULT_TREATMENT": "2026-11-20T00:00:00Z",
}

TEST_DEFAULTS = {
    "SPONSOR_EIN": "123456789",
    "BALANCE_CENTS": 250000,
    "MAILING_ADDRESS": "1 Main St",
}
