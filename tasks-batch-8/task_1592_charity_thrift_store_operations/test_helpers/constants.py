"""Domain thresholds and lookup tables stated in the PRD.

All numbers come from PRD sections 3.1-3.9 (fair-market figures, price
multipliers, markdown discounts, commodity default rates, variance band,
receipt thresholds, hour caps, reserve tiers).
"""

# PRD 3.1 - intake provisional valuation
CATEGORY_FMV_CENTS = {
    "CLOTHING": 800,
    "FURNITURE": 4500,
    "ELECTRONICS": 3000,
    "HOUSEWARES": 1200,
    "BOOKS_MEDIA": 300,
    "TOYS": 600,
    "COLLECTIBLES": 5000,
}
CONDITION_VALUE_MULT = {
    "NEW_WITH_TAGS": 1.0,
    "GOOD": 0.7,
    "FAIR": 0.4,
    "POOR": 0.15,
}

# PRD 3.3 - suggested pricing
CONDITION_PRICE_MULT = {
    "NEW_WITH_TAGS": 1.0,
    "GOOD": 0.8,
    "FAIR": 0.6,
    "POOR": 0.35,
}
COLLECTIBLES_MULT_FLOOR = 1.2
MIN_PRICE_CENTS = 100
MAX_PRICE_CENTS = 500000
HIGH_VALUE_PRICE_CENTS = 10000

# PRD 3.4 - markdown cadence / cycle close
MARKDOWN_OFF = {1: 0.25, 2: 0.50, 3: 0.75}
MAX_MARKDOWN_ROUND = 3
HOLD_HOURS = 72
SHRINK_ALERT_BP = 300

# PRD 3.5 - salvage bales
DEFAULT_EST_RATE_CENTS = {"TEXTILES": 12, "PAPER": 6, "EWASTE": 3, "BULK": 2}
BALE_MIN_SEAL_LBS = 100.0

# PRD 3.6 - till reconciliation
AUTO_RECONCILE_MAX_CENTS = 500

# PRD 3.7 - pickup routes
TRAVEL_BUFFER_MINUTES = 30

# PRD 3.8 - workforce caps
WEEKLY_CAP_HOURS = 20.0
DEFAULT_PROGRAM_CAP_HOURS = 480

# PRD 3.9 - receipts and mission transfers
ITEMIZED_THRESHOLD_CENTS = 25000
FORM_8283_THRESHOLD_CENTS = 50000
APPRAISAL_THRESHOLD_CENTS = 500000
RESERVE_TIER_1_MAX_CENTS = 100000
RESERVE_TIER_2_MAX_CENTS = 500000
RESERVE_PCT_T1 = 10
RESERVE_PCT_T2 = 15
RESERVE_PCT_T3 = 20

# PRD 2.5 - logical clock default
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD 2.7 - rotation color by sequence remainder mod 4
ROTATION_COLOR_BY_REMAINDER = {1: "RED", 2: "BLUE", 3: "GREEN", 0: "YELLOW"}
