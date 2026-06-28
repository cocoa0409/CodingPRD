"""Domain thresholds and shared numeric constants from PRD calculations."""

# Clock default at server startup (PRD §3.7).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# RecurringBill due-day domain (PRD §3.7).
DAY_OF_MONTH_MIN = 1
DAY_OF_MONTH_MAX = 28

# Recurring-bill slot-conflict adjacency buffer (PRD §3.7).
BILL_SLOT_BUFFER_DAYS = 2

# Cash-flow forecast horizon domain (PRD §3.7).
HORIZON_DAYS_MIN = 1
HORIZON_DAYS_MAX = 90

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

TEST_DEFAULTS = {
    "OPENING_BALANCE": 50000,
    "ALLOCATED": 10000,
}
