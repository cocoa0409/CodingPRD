"""Domain thresholds — numeric constants from PRD calculations."""

# Standings scoring (PRD §3.5)
MATCH_WIN_POINTS = 3
MATCH_DRAW_POINTS = 1
MATCH_LOSS_POINTS = 0

# Station scheduling turnover buffer, minutes (PRD §2.10 / §3.4)
STATION_TURNOVER_MINUTES = 15

# Backup withholding (PRD §3.8)
TAX_RATE_NO_ID = 0.24
TAX_RATE_WITH_ID = 0.00

# Payout percentage split table by paid_places (PRD §3.8)
PAYOUT_PCT = {
    1: [1.00],
    2: [0.70, 0.30],
    3: [0.50, 0.30, 0.20],
    4: [0.40, 0.30, 0.20, 0.10],
}

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Default fixture dates (logical clock starts at 2026-07-01T00:00:00Z)
DEFAULT_CHECK_IN_DEADLINE = "2026-08-01T00:00:00Z"
