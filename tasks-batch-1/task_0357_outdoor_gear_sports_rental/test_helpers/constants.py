"""Domain thresholds — numeric constants from the PRD's pricing and standing rules."""

# Demand multiplier default when no season applies (PRD §2.7, §3.3): 10000 bp = x1.0.
DEFAULT_MULTIPLIER_BP = 10000

# Add-on bundle discount (PRD §3.4): >= 2 PACKAGE lines -> each line x0.95.
BUNDLE_DISCOUNT_RATE = 0.95
BUNDLE_MIN_PACKAGES = 2

# Damage charge fraction (PRD §3.6): DAMAGE charge = round(loss_fee_cents * 0.40).
DAMAGE_FRACTION = 0.40

# Window-overlap turnaround buffer (PRD §3.3): existing window extended by 30 min.
TURNAROUND_MINUTES = 30

# Customer standing strike weights and thresholds (PRD §3.2).
LATE_STRIKE = 1
DAMAGE_STRIKE = 2
LOSS_STRIKE = 4
WATCH_AT = 2
SUSPEND_AT = 4

# Default grace period (PRD §3.1): rate card grace_minutes defaults to 15.
DEFAULT_GRACE_MINUTES = 15

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
DEFAULT_OFFSET = 0


# A canonical rate card used across most fixtures. Chosen so that:
#   - a 2h window: hourly base = 1000*2 = 2000, daily base = 3000*1 = 3000,
#     seasonal = 20000 -> cheapest HOURLY = 2000.
TEST_DEFAULTS = {
    "HOURLY_CENTS": 1000,
    "DAILY_CENTS": 3000,
    "SEASONAL_FLAT_CENTS": 20000,
    "DEPOSIT_CENTS": 5000,
    "DAMAGE_WAIVER_CENTS_PER_DAY": 400,
    "LATE_FEE_CENTS_PER_HOUR": 800,
    "LOSS_FEE_CENTS": 20000,
    "GRACE_MINUTES": 15,
}
