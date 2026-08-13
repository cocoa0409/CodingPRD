"""Domain thresholds from PRD §2.6 and §3 (scoring bands, caps, limits)."""

# Band edges (PRD §2.6): LOW 1-4, MEDIUM 5-9, HIGH 10-15, CRITICAL 16-25
THRESHOLDS = {
    "BAND_LOW_MAX": 4,
    "BAND_MEDIUM_MAX": 9,
    "BAND_HIGH_MAX": 15,
    "SCORE_MAX": 25,
    # Discount cap on residual scoring (PRD §3.3)
    "DISCOUNT_CAP": 0.90,
    # Promotion threshold (PRD §3.7)
    "PROMOTE_THRESHOLD": 10,
    # Default logical clock before any POST /_clock/set_current_utc (PRD §2.4)
    "DEFAULT_CLOCK_UTC": "2026-08-01T00:00:00Z",
    # Plan extension limit (PRD §3.5)
    "MAX_PLAN_EXTENSIONS": 3,
    # Pagination (PRD §2.3)
    "PAGE_LIMIT_DEFAULT": 10,
    "PAGE_LIMIT_MAX": 100,
}

TEST_DEFAULTS = {
    "TREATMENT_BUDGET_CENTS": 1_000_000,
    "PLAN_BUDGET_CENTS": 100_000,
}
