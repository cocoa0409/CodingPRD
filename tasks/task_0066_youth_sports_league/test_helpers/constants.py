"""Domain thresholds — numeric constants from the PRD's calculations (§3)."""

# Evaluation weighted-score blend weights (PRD §3.3).
W_HITTING = 0.50
W_FIELDING = 0.30
W_SPEED = 0.20

# Evaluation tier thresholds (inclusive lower bounds) (PRD §3.3).
TIER_A_MIN = 70.00
TIER_B_MIN = 55.00
TIER_C_MIN = 40.00

# Volunteer settlement admin fee (PRD §3.8).
ADMIN_FEE_PCT = 0.05

# Field default turnover buffer in minutes (PRD §3.1, §3.5).
DEFAULT_TURNOVER_BUFFER_MINUTES = 30

# Referee default daily cap (PRD §3.1, §3.7).
DEFAULT_MAX_GAMES_PER_DAY = 3

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
