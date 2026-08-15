"""Domain thresholds and shared values — numeric constants from PRD rules."""

# PRD §2.5: startup value of the server-side logical clock.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Common logical-clock waypoints used by repayment / rating-window scenarios.
DATES = {
    "AUTHORIZE_DEFAULT": "2026-08-01T00:00:00Z",
    "TERMINATE_AT": "2027-02-01T00:00:00Z",   # 18 months before a 24-month window ending 2028-08-01
    "SIGN_AT": "2027-02-15T00:00:00Z",
    "PAST_DUE_AT": "2027-04-01T00:00:00Z",    # past next_due_date 2027-03-15
    "ROLLING_WINDOW_START": "2026-09-01T00:00:00Z",
    "THIRTEEN_MONTHS_LATER": "2027-09-01T00:00:00Z",
}

# Canonical amounts shared across repayment scenarios: a 61000-cent COMPLETED
# travel booking, an 18/24 proration (owed 45750), and its 24-installment
# floor-then-remainder schedule (1906 regular, 1912 final).
AMOUNTS = {
    "TRAVEL_PAID": 61000,
    "TOTAL_OWED": 45750,
    "INSTALLMENT": 1906,
    "FINAL_INSTALLMENT": 1912,
    "INSTALLMENTS_COUNT": 24,
}

THRESHOLDS = {
    "TEMP_HOUSING_MAX_NIGHTS": 30,
    "MISC_CAP_CENTS": 200000,
    "HHG_CAP_CENTS": 500000,
    "TEMP_HOUSING_CAP_CENTS": 300000,
    "TRAVEL_CAP_CENTS": 100000,
    "LOSS_ON_SALE_CAP_CENTS": 4000000,
    "MARGINAL_BRACKET_CENTS": 100000,
}

TEST_DEFAULTS = {
    "FLAT_GROSS_UP_RATE": 0.22,
    "MARGINAL_RATE_LOW": 0.25,
    "MARGINAL_RATE_HIGH": 0.4,
}
