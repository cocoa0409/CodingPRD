"""Domain thresholds — numeric constants from PRD calculations."""

# Investigation deadline (PRD §3.4 / §2.9)
CALENDAR_DAYS = 30
EXPEDITED_BUSINESS_DAYS = 15

# Purge window (PRD §3.2): DOFD + 7*365 days + 180 days
PURGE_YEARS_DAYS = 2555  # 7 * 365
PURGE_PLUS_DAYS = 180

# Priority score (PRD §3.4)
REASON_WEIGHT = {
    "IDENTITY_THEFT": 50,
    "ILLEGAL_REAGE": 40,
    "NOT_MINE": 35,
    "INACCURATE_BALANCE": 20,
    "PAID_IN_FULL": 15,
}
REAGE_BONUS = 25
BALANCE_CENTS_PER_POINT = 50000
BALANCE_POINT_CAP = 20
REOPEN_PENALTY_PER_CYCLE = 10
PRIORITY_SCORE_MIN = 0
PRIORITY_SCORE_MAX = 100

# Reopen limit (PRD §3.6): a dispute may be reopened at most twice
REOPEN_LIMIT = 2

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
