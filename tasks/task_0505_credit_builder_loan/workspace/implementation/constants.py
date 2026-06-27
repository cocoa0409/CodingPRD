"""Domain constants pinned from PRD §3 / SCAFFOLD calculations."""

# Loan product bounds (PRD §3.3)
SUPPORTED_TERMS = (12, 24)
MIN_PRINCIPAL_CENTS = 30000
MAX_PRINCIPAL_CENTS = 300000

# Graduation (PRD §3.6)
GRADUATION_MIN_STREAK = 6

# Secured card deposit bounds (PRD §3.9)
MIN_CARD_DEPOSIT_CENTS = 20000
MAX_CARD_DEPOSIT_CENTS = 250000

# State APR caps in basis points (PRD §3.1)
STATE_APR_CAP_BPS = {"CA": 3600, "NY": 2500, "TX": 9999, "FL": 3000}
SUPPORTED_STATES = ("CA", "NY", "TX", "FL")

# Late fees / grace (PRD §3.5)
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

BUREAUS = ["EQUIFAX", "EXPERIAN", "TRANSUNION"]

ROLES = ("Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin")

# Logical clock default at startup (PRD §2.9)
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"
