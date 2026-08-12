"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD 2.5): when the clock-positioning capability
# has never been invoked, the logical clock reads exactly this instant.
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Late-return fee (PRD 3.5)
LATE_FEE_PER_DAY_CENTS = 150

# Wishlist holds (PRD 3.4)
HOLD_WINDOW_HOURS = 72

# Sanitization protocol (PRD 2.10)
SANITIZATION_VALIDITY_DAYS = 30
SANITIZATION_MIN_HOURS = 24

# Fee disputes (PRD 3.8)
MAX_DISPUTE_ROUNDS = 2

# Pause allowance (PRD 3.3)
MAX_PAUSE_DAYS_PER_365 = 60

# Wallet suspension (PRD 2.9): strictly below -5000 suspends; exactly -5000 stays ACTIVE.
SUSPENSION_THRESHOLD_CENTS = 5000

# Buy-out pricing (PRD 3.7)
MIN_NET_CHARGE_CENTS = 100
MIN_BUYOUT_FLOOR_CENTS = 499
RENTAL_CREDIT_PCT_PER_MONTH = 0.04
RENTAL_CREDIT_CAP_PCT = 0.30
GRADE_DEPRECIATION = {"NEW": 1.0, "GOOD": 0.85, "FAIR": 0.70, "WORN": 0.55}

# Inspection fee rates (PRD 3.6)
DAMAGE_RATE = {"MINOR": 0.15, "MODERATE": 0.35, "SEVERE": 0.75}

# Developmental stage bands in whole calendar months (PRD 3.1)
STAGE_BAND_TODDLER_MIN = 12
STAGE_BAND_PRESCHOOLER_MIN = 36
STAGE_BAND_EARLY_SCHOOL_MIN = 60

# Shared fixture defaults.  The STD plan mirrors the design fixtures:
# 2 slots, 2 swaps, 2 holds, 28-day cadence, 28-day rental, 10% buy-out discount.
STD_PLAN = {
    "name": "STD",
    "monthly_fee_cents": 5000,
    "toys_per_box": 2,
    "swap_allowance_per_cycle": 2,
    "max_holds": 2,
    "rotation_cadence_days": 28,
    "rental_period_days": 28,
    "buyout_discount_pct": 0.10,
}

# A toddler-aged child at the default clock: born 2025-01-15 -> 15 calendar
# months on 2026-05-01, inside the usual [12, 36] catalog window.
DEFAULT_CHILD_BIRTHDATE = "2025-01-15"
DEFAULT_ITEM_AGE_WINDOW = (12, 36)
