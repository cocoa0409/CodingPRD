"""Domain thresholds — numeric constants drawn from the PRD's calculations."""

# Table time is billed in 30-minute blocks; any started block counts fully (PRD §3.3).
TIME_BLOCK_MINUTES = 30

# Loyalty discount percentage keyed on tier_at_seating (PRD §3.3).
DISCOUNT_PCT = {
    "BRONZE": 0.00,
    "SILVER": 0.10,
    "GOLD": 0.20,
}

# One loyalty point per 100 cents of F&B spend, floored per line (PRD §3.3).
POINTS_PER_CENT_DIVISOR = 100

# Tier thresholds on lifetime_points, inclusive lower bound (PRD §3.1).
TIER_SILVER_THRESHOLD = 500
TIER_GOLD_THRESHOLD = 2000

# Tournament house cut on gross entry fees (PRD §3.6).
HOUSE_CUT_PCT = 0.20

# Return-fee charge per grade of condition degradation (PRD §3.5).
CONDITION_STEP_CENTS = 800
CONDITION_ORDINALS = {"MINT": 0, "GOOD": 1, "WORN": 2, "DAMAGED": 3, "LOST": 4}

# Private-booking quote components (PRD §3.7).
PER_HEAD_CATERING_CENTS = 1500
SERVICE_FEE_PCT = 0.18
DEPOSIT_PCT = 0.25

# No-show strikes that suspend a membership (PRD §3.4).
NO_SHOW_SUSPEND_THRESHOLD = 3

# Reservation cancellation cutoff before the window start (PRD §3.4).
CANCEL_CUTOFF_MINUTES = 120

# Table turnover buffer applied on both sides of a reservation window (PRD §2.7).
TABLE_TURNOVER_BUFFER_MINUTES = 15

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Logical-clock startup default (PRD §2.4).
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"
