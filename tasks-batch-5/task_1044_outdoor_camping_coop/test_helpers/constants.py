"""Domain thresholds — numeric constants from the PRD calculations (§2.5–§2.6, §3)."""

# Logical clock
CLOCK_STARTUP_DEFAULT = "2026-07-01T00:00:00Z"

# Membership join fees (§3.1)
JOIN_FEE_BASIC_CENTS = 3000
JOIN_FEE_PREMIER_CENTS = 12000

# Rental fee calculation (§3.3)
PEAK_START = "2026-06-01T00:00:00Z"
PEAK_END = "2026-09-01T00:00:00Z"
PEAK_MULTIPLIER = 1.25
TIER_RENTAL_DISCOUNT = {"BASIC": 0.00, "PREMIER": 0.10}
TURNAROUND_BUFFER_DAYS = 1

# Purchase totals / loyalty (§3.2)
MAX_REDEEM_PCT = 0.50
POINTS_PER_CENT = 0.01

# Dividend (§3.9)
PROVISIONAL_RATE = 0.05
MIN_ELIGIBLE_SPEND_CENTS = 100000

# Trade-in valuation (§3.5)
GRADE_FACTOR = {"A": 0.50, "B": 0.35, "C": 0.20}
CASH_FACTOR = 0.80
CREDIT_FACTOR = 1.00
MAX_TRADE_IN_ROUNDS = 3

# Special-order deposit (§3.8)
SPECIAL_ORDER_DEPOSIT_PCT = 0.20

# Warranty (§3.6)
WARRANTY_DAYS = 365
