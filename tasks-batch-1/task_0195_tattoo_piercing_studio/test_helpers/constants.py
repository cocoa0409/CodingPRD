"""Domain thresholds — numeric constants drawn from the PRD calculations and
business rules (§2.8, §3.2, §3.6, §3.9, §3.10). Generic NON_EXISTENT_UUID
comes from the framework.
"""

# Deposit calculation (PRD §3.6)
DEPOSIT_RATE = 0.20          # 20% of the session estimate
DOLLAR_CENTS = 100          # required deposit rounds up to a whole dollar

# Session gross / hourly billing (PRD §3.9)
INCREMENT_MINUTES = 15      # billed in 15-minute increments
HOURLY_DIVISOR = 4         # per-increment = hourly_rate_cents / 4

# Final balance (PRD §3.9)
TAX_RATE = 0.08            # 8% tax on the post-deposit balance

# Payout (PRD §3.9)
SUPPLY_FEE_CENTS = 3500    # flat supply fee deducted from the artist cut

# Reliability score (PRD §3.9)
CANCEL_WEIGHT = 5          # points per artist cancellation
RESCHED_WEIGHT = 10        # points per late reschedule
SCORE_FLOOR = 0
SCORE_BASE = 100

# Age gate (PRD §3.2)
MIN_AGE_YEARS = 18

# Touch-up free-window policy (PRD §3.10)
FREE_WINDOW_DAYS = 90
TOUCHUP_FLAT_FEE_CENTS = 6000

# Default chair sanitation buffer (PRD §3.1)
DEFAULT_CLEANUP_BUFFER_MINUTES = 30

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100


THRESHOLDS = {
    "DEPOSIT_RATE": DEPOSIT_RATE,
    "INCREMENT_MINUTES": INCREMENT_MINUTES,
    "TAX_RATE": TAX_RATE,
    "SUPPLY_FEE_CENTS": SUPPLY_FEE_CENTS,
    "CANCEL_WEIGHT": CANCEL_WEIGHT,
    "RESCHED_WEIGHT": RESCHED_WEIGHT,
    "MIN_AGE_YEARS": MIN_AGE_YEARS,
    "FREE_WINDOW_DAYS": FREE_WINDOW_DAYS,
    "TOUCHUP_FLAT_FEE_CENTS": TOUCHUP_FLAT_FEE_CENTS,
}
