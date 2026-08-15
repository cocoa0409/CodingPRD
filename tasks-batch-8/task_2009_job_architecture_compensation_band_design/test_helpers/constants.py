"""Domain thresholds — numeric constants stated in PRD §2.5 and §3.

Only constants whose values the PRD names verbatim belong here. The two
FLSA statutory floors are server-configured per PRD §2.5 and have no
PRD-stated numeric value, so they are intentionally absent.
"""

THRESHOLDS = {
    # PRD §2.5: escalation rate 3% per year, prorated by whole months.
    "ESCALATION_RATE": 0.03,
    # PRD §2.5: percentile factors 1.00 / 1.06 / 1.12.
    "PERCENTILE_FACTOR_P50": 1.0,
    "PERCENTILE_FACTOR_P62_5": 1.06,
    "PERCENTILE_FACTOR_P75": 1.12,
    # PRD §2.5: default max overlap 30% and default min progression 10%.
    "DEFAULT_MAX_OVERLAP_PCT": 0.3,
    "DEFAULT_MIN_PROGRESSION_PCT": 0.1,
    # PRD §2.5: guidance zone bounds 0.8 and 1.2 of midpoint.
    "GUIDANCE_LOW": 0.8,
    "GUIDANCE_HIGH": 1.2,
    # PRD §2.5: exception cap tiers 110% / 105% / 100% of band max.
    "CAP_TIER_LOW": 1.1,
    "CAP_TIER_MID": 1.05,
    "CAP_TIER_HIGH": 1.0,
    # PRD §2.6: reversal window is 30 days; cut spacing 30 days;
    # rolling exception window 365 days; fewer than 2 in-window requests.
    "REVERSE_WINDOW_DAYS": 30,
    "CUT_SEPARATION_DAYS": 30,
    "ROLLING_CAP_DAYS": 365,
    "ROLLING_CAP_MAX_IN_WINDOW": 2,
}

TEST_DEFAULTS = {
    "FISCAL_YEAR": 2027,
    "MERIT_BUDGET_CENTS": 50_000_000,
    "REFRESH_BUDGET_CENTS": 2_000_000,
    "PRICING_AS_OF_DATE": "2026-08-01",
    "DEPARTMENT_POOL_CENTS": 5_000_000,
    "ZONE_RATIO_ROOT": 1.000000,
    "SPREAD_PCT": 0.3000,
    "SAMPLE_SIZE": 20,
    "WEEKLY_BASIS_EXEMPT": 200_000,
    "WEEKLY_BASIS_NON_EXEMPT": 60_000,
    # Logical clock startup default (PRD §2.6).
    "CLOCK_START_ISO": "2026-08-01T00:00:00Z",
}
