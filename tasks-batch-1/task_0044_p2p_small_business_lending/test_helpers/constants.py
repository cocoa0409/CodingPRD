"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Scoring weights (PRD §3.2)
SCORE_WEIGHTS = {
    "W_DSCR": 0.40,
    "W_STAB": 0.30,
    "W_NSF": 0.20,
    "W_AGE": 0.10,
}
DSCR_FULL_RATIO = 2.0
NSF_PENALTY_PER_EVENT = 15.0
AGE_FULL_MONTHS = 60
DSCR_ZERO_DEBT_RATIO = 3.0

# Grade thresholds — inclusive lower bounds on credit_score (PRD §3.2)
GRADE_THRESHOLDS = {
    "A": 85,
    "B": 70,
    "C": 55,
    "D": 40,
    # below 40 -> F
}

# APR by grade as decimal fractions (PRD §3.2); grade F -> null
APR_BY_GRADE = {
    "A": 0.0599,
    "B": 0.0899,
    "C": 0.1299,
    "D": 0.1799,
    "F": None,
}

# Servicing fee (PRD §3.6)
SERVICING_FEE_PCT = 0.01

# Late fee (PRD §3.7)
LATE_FEE_PCT = 0.05
LATE_FEE_FLOOR_CENTS = 2500

# Default trigger (PRD §3.7): third successful assessment escalates to DEFAULTED
DEFAULT_MISSED_PAYMENT_THRESHOLD = 3

# Diversification cap default (PRD §3.4)
DEFAULT_MAX_SINGLE_LOAN_PCT = 0.25

# Investment minimums / bounds (PRD §3.1, §3.4)
MIN_INVESTMENT_AMOUNT_CENTS = 2500
MIN_REQUESTED_PRINCIPAL_CENTS = 100000
MAX_REQUESTED_PRINCIPAL_CENTS = 50000000
ALLOWED_TERM_MONTHS = (12, 24, 36, 60)

MONTHS_PER_YEAR = 12

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
DEFAULT_OFFSET = 0

# Common large deposit used across funding fixtures.
BIG_DEPOSIT_CENTS = 5_000_000
