"""Domain thresholds — numeric constants from PRD calculations and bounds."""

# Loan product bounds (PRD §3.3)
MIN_PRINCIPAL_CENTS = 30000
MAX_PRINCIPAL_CENTS = 300000
SUPPORTED_TERMS = [12, 24]

# Graduation (PRD §3.6)
GRADUATION_MIN_STREAK = 6

# Secured-card deposit bounds (PRD §3.9)
MIN_CARD_DEPOSIT_CENTS = 20000
MAX_CARD_DEPOSIT_CENTS = 250000

# State APR usury caps in basis points (PRD §3.1)
STATE_APR_CAP_BPS = {"CA": 3600, "NY": 2500, "TX": 9999, "FL": 3000}
SUPPORTED_STATES = ["CA", "NY", "TX", "FL"]

# Late fees (PRD §3.5)
LATE_FEE_CENTS = 1500
LATE_FEE_CAP_CENTS = 4500
GRACE_DAYS = 5

# Payoff (PRD §3.8)
DAYS_PER_MONTH = 30
QUOTE_TTL_HOURS = 24

# Score model (PRD §3.12)
SCORE_BASE = 580
PAYMENT_HISTORY_PTS = 6
LATE_PENALTY_PTS = 40
UTILIZATION_MAX_PTS = 120
AGE_CAP_MONTHS = 24
AGE_PTS_PER_MONTH = 2

# The three national bureaus (PRD §3.12)
BUREAUS = ["EQUIFAX", "EXPERIAN", "TRANSUNION"]

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10

# Server startup logical clock default (PRD §2.9)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"
