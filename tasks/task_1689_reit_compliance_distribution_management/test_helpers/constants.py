"""Domain thresholds — numeric constants named in PRD §2.5 and §3.

Percentages are computed to four decimal places round-half-up (PRD §2.5);
threshold comparisons are inclusive at the stated boundary.
"""

THRESHOLDS = {
    # PRD §3.3: 75% asset test boundary (inclusive)
    "ASSET_TEST_75_PCT": 75.0000,
    # PRD §3.3: TRS concentration limit (inclusive; 20.0001 breaches)
    "TRS_LIMIT_PCT": 20.0000,
    # PRD §3.3: income test boundaries (inclusive)
    "INCOME_TEST_75_PCT": 75.0000,
    "INCOME_TEST_95_PCT": 95.0000,
    # PRD §3.4: 5/50 concentration cap (inclusive)
    "FIVE_FIFTY_LIMIT_PCT": 50.0000,
    # PRD §3.8: prohibited-transaction safe harbor in months
    "SAFE_HARBOR_MONTHS": 24,
    # PRD §3.5: 90% distribution requirement ratio
    "REQUIRED_DISTRIBUTION_RATIO": 0.90,
    # PRD §3.1: charter_ownership_limit_pct must lie strictly between 0 and this
    "CHARTER_LIMIT_EXCLUSIVE_MAX": 50.0,
    # PRD §2.7: logical clock reads exactly this before any set call
    "DEFAULT_CLOCK_UTC": "2026-08-01T00:00:00Z",
}

TEST_DEFAULTS = {
    "CHARTER_LIMIT_PCT": 9.8,
    "TAXABLE_YEAR": 2026,
    "HALF_YEAR_END_H1": "2026-06-30",
    "HALF_YEAR_END_H2": "2026-12-31",
}
