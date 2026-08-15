"""Domain thresholds — numeric constants stated in PRD section 3.5 prose."""

# Variance alert thresholds in basis points (PRD 3.5: five percent WATCH,
# ten percent WARNING, twenty percent BREACH; a value exactly on a threshold
# escalates).
THRESHOLDS = {
    "WATCH_THRESHOLD_BP": 500,
    "WARNING_THRESHOLD_BP": 1000,
    "BREACH_THRESHOLD_BP": 2000,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK": "2026-08-01T00:00:00Z",
    "FISCAL_YEAR_INDEX": 2026,
    "FISCAL_YEAR_START_MONTH": 1,
    "ENTRY_DATE": "2026-08-05",
    "NEXT_PERIOD_ENTRY_DATE": "2026-09-03",
    "AFTER_YEAR_END_CLOCK": "2027-02-01T00:00:00Z",
    "STANDARD_RATE_CENTS": 50000,
    "BUDGET_CENTS": 100000,
}
