"""Domain thresholds — numeric constants from PRD calculations (§2.7, §3.3)."""

# Production cost (PRD §2.7): per-page rate is 7.3 cents; round per document then sum.
PER_PAGE_RATE_CENTS = 7.3

# Bates label rendering (PRD §2.7): sequence zero-padded to six digits.
BATES_PAD_WIDTH = 6

# Spoliation risk scoring constants (PRD §3.3).
PER_UNACK_WEIGHT = 15      # fifteen points per unacknowledged custodian
PER_DAY_WEIGHT = 2         # two points per whole day since issuance
DAYS_CAP = 30              # day term uses min(D, 30)
TIER_LOW = 100             # mult 1.0 when R < 100
TIER_HIGH = 1000           # mult 1.2 when 100 <= R < 1000; 1.5 when R >= 1000
SCORE_CEILING = 100        # score capped at 100

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
