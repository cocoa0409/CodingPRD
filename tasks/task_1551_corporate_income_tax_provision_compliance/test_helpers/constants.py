"""Domain thresholds — numeric constants named in the PRD's calculation rules."""

# PRD §3.4: recognition requires strictly greater than 5000 basis points.
UTP_RECOGNITION_THRESHOLD_BP = 5000
# PRD §3.4: interest accrues at 500 basis points per annum (5%).
UTP_INTEREST_RATE_BP = 500
# PRD §3.5: the late-payment penalty is 400 basis points (4%) of the shortfall.
LATE_PENALTY_RATE_BP = 400
# PRD §3.5: the safe-harbor estimate is 100% of prior-year tax.
SAFE_HARBOR_PCT_BP = 10000
# PRD §2.7/§3.4: a disclosed position lapses three years past filed_on.
STATUTE_YEARS = 3

# PRD §2.7: the logical clock's startup default.
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "PRETAX_BOOK_INCOME_CENTS": 100000000,
    "PRIOR_YEAR_TOTAL_TAX_CENTS": 8000000,
    "ENACTED_FEDERAL_RATE_BP": 2100,
    # Illinois-style annualized quarter: round(100,000,000 * 2503 * 883 / 1e8)
    # spread over four quarters by the pinned cumulative rounding rule.
    "IL_ANNUAL_ESTIMATE_CENTS": 2210149,
    "IL_Q1_SCHEDULED_CENTS": 552537,
    "IL_Q2_SCHEDULED_CENTS": 552538,
    # New-York-style safe-harbor quarter: round(8,000,000 * 2503 * 10000 / 1e8)
    # = 2,002,400 per year -> 500,600 per quarter.
    "NY_SAFE_HARBOR_ANNUAL_CENTS": 2002400,
    "NY_SAFE_HARBOR_QUARTER_CENTS": 500600,
}
