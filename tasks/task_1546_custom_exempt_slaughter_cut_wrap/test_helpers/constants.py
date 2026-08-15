"""Domain thresholds and rate constants from PRD §2.4 and §3."""

# Logical clock default at server startup (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Booking / deposit (PRD §3.1, §3.2).
MIN_LEAD_DAYS = 14
DEPOSIT_WINDOW_HOURS = 48
DEPOSIT_FLAT_PER_HEAD_CENTS = {"BEEF": 15000, "HOG": 7500, "LAMB": 5000, "GOAT": 5000}
AVG_LIVE_WEIGHT_LBS = {"BEEF": 1200, "HOG": 280, "LAMB": 130, "GOAT": 90}
DRESS_PCT = {"BEEF": 0.62, "HOG": 0.75, "LAMB": 0.52, "GOAT": 0.50}
ELEVATED_DEPOSIT_PCT = 0.50
SLAUGHTER_FEE_CENTS = {"BEEF": 12000, "HOG": 6000, "LAMB": 4500, "GOAT": 4500}

# Tiered processing (PRD §3.6).
TIER1_MAX_LBS = 200
RATE_A_CENTS_PER_LB = {"BEEF": 95, "HOG": 85, "LAMB": 110, "GOAT": 110}
RATE_B_CENTS_PER_LB = {"BEEF": 85, "HOG": 75, "LAMB": 95, "GOAT": 95}

# Cut instructions (PRD §3.4).
MAX_GRIND_PCT = 60

# Fabrication / freezer (PRD §3.5).
MIN_HANG_DAYS = 3
FREEZER_CAPACITY_UNITS = 4
FREEZER_UNITS_PER_SHARE = 1

# Storage accrual (PRD §3.5).
FREE_STORAGE_DAYS = 7
STORAGE_DAILY_CENTS = 500

# Cancellation (PRD §3.2).
CANCEL_FULL_REFUND_DAYS = 7

# Abandonment / strikes (PRD §3.8).
ABANDON_AFTER_DAYS = 21
ABANDON_SURCHARGE_CENTS = 5000
STRIKE_BLOCK_THRESHOLD = 2

# Default clock dates used across tests.
DAY_0820 = "2026-08-20"
FABRICATION_DAY = "2026-08-04T00:00:00Z"
