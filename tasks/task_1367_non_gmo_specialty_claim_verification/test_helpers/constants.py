"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # ClaimStandard defaults (PRD section 3.1)
    "DEFAULT_AUDIT_VALIDITY_MONTHS": 12,
    "DEFAULT_RENEWAL_WINDOW_DAYS": 60,
    "DEFAULT_LICENSE_TERM_DAYS": 365,
    # required_sample_count formula constants (PRD section 3.5)
    "MAX_SAMPLES": 10,
    "BASE_INGREDIENT_INTAKE": 0,
    "BASE_IN_PROCESS": 1,
    "BASE_FINISHED_PRODUCT": 2,
    "VOLUME_TIER_1": 10000,
    "VOLUME_TIER_2": 100000,
    "HISTORY_EXTRA": 2,
    # Traceability exercise (PRD section 3.6)
    "TRACE_PASS_MIN_SCORE": 95.00,
    # Penalty points (PRD section 3.8)
    "PENALTY_WARNING": 5,
    "PENALTY_LICENSE_SUSPENSION": 15,
    "PENALTY_LICENSE_REVOCATION": 25,
    "PROBATION_LIFETIME_POINTS": 20,
    "RECENT_PENALTIES_BLOCK": 10,
    # Standard NGMO thresholds used across fixtures
    "INGREDIENT_THRESHOLD_PCT": 0.9,
    "EXEMPTION_MAX_WEIGHT_PCT": 0.5,
}

# The logical clock boots at exactly this instant (PRD section 2.6).
CLOCK_BOOT_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "ANNUAL_VOLUME_UNITS": 100,
    "RESULT_GMO_PCT_COMPLIANT": 0.10,
}
