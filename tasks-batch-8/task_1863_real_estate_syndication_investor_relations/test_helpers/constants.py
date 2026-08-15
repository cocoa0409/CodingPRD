"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

THRESHOLDS = {
    # §3.5: distributable cash = NOI - 10% reserve - 30% debt service
    "RESERVE_PCT": 0.10,
    "DEBT_SERVICE_PCT": 0.30,
    # §3.8: compounding accrual applies when carried_interest_pct >= 0.25
    "COMPOUNDING_CARRY_THRESHOLD": 0.25,
    # §3.8: four quarters per year in both accrual variants
    "QUARTERS_PER_YEAR": 4,
    # §3.3: commitments of 100000 dollars (10,000,000 cents) or more require
    # ACCREDITED or QUALIFIED_PURCHASER
    "INVESTOR_CLASS_THRESHOLD_CENTS": 10_000_000,
    # §3.9: portal sessions live for twelve hours
    "PORTAL_SESSION_TTL_HOURS": 12,
    # §3.3: accreditation verification stamps expiry ninety days out
    "ACCREDITATION_VALIDITY_DAYS": 90,
}

TEST_DEFAULTS = {
    "PREFERRED_RETURN_PCT_ANNUAL": 0.08,
    "CARRIED_INTEREST_PCT": 0.20,
    "MIN_SUBSCRIPTION_CENTS": 10_000,
    "MAX_NON_ACCREDITED_COUNT": 35,
    "COMMITTED_CENTS": 5_000_000,
    "DEFAULT_DUE_DATE": "2027-01-01T00:00:00Z",
    # Server boots at 2026-08-01T00:00:00Z before any clock adjustment (§2.8).
    "BOOT_CLOCK_UTC": "2026-08-01T00:00:00Z",
}
