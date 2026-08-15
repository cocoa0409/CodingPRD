"""Domain thresholds and shared values — numeric constants named in PRD §2 and §3."""

THRESHOLDS = {
    # Fairness gate at plan approval (PRD §3.7)
    "FAIRNESS_TOLERANCE_BP": 200,
    # Fairness deviation cap when a pro-rata ideal is zero (PRD §3.7)
    "DEVIATION_CAP_BP": 99999,
    # Basis-point denominator for commissions (PRD §3.7)
    "BP_DENOMINATOR": 10000,
    # Settlement lags in calendar days (PRD §3.9)
    "EQUITY_LAG_DAYS": 1,
    "FIXED_INCOME_LAG_DAYS": 2,
    # Fail monitor grace and escalation (PRD §3.9)
    "FAIL_GRACE_DAYS": 1,
    "FAIL_ESCALATION_THRESHOLD": 2,
}

TEST_DEFAULTS = {
    # PRD §2.5: startup default of the desk logical clock
    "CLOCK_START": "2026-08-01T00:00:00Z",
    # Budget window covering every trade date used by the suites
    "BUDGET_PERIOD_START": "2026-01-01",
    "BUDGET_PERIOD_END": "2027-01-01",
    "BUDGET_AMOUNT_CENTS": 100000,
    "COMMISSION_RATE_BP": 50,
    "FILL_EXECUTED_AT": "2026-08-01T09:00:00Z",
    # Conventional operator ids; the segregation-of-duties pair must differ
    "TRADER_USER_ID": "trader-1",
    "APPROVER_USER_ID": "co-1",
}
