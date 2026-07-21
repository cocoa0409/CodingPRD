"""Domain thresholds and pricing constants from the PRD calculations (PRD §2.6, §2.9, §3.3, §3.4, §3.6)."""

# --- Longarm pricing (PRD §3.4) ---
LONGARM_TIER_RATES = {
    "EDGE_TO_EDGE": 0.02,
    "CUSTOM": 0.035,
    "HEIRLOOM": 0.05,
}
LARGE_AREA_THRESHOLD = 7500      # area strictly greater than this triggers the surcharge
LARGE_SURCHARGE = 1.1
BATTING_FEE = 25
THREAD_FEE = 12
RUSH_MULTIPLIER = 1.25
MIN_CHARGE = 30

# --- Special-order pricing (PRD §3.6) ---
SPECIAL_ORDER_MARKUP = 1.5

# --- Kit pricing (PRD §3.3) ---
KIT_MARKUP = 1.4

# --- Loyalty (PRD §2.9) ---
POINTS_PER_DOLLAR = 10
SILVER_THRESHOLD = 1000
GOLD_THRESHOLD = 5000

# --- Longarm scheduling (PRD §3.4) ---
SETUP_BUFFER_MINUTES = 30

# --- Fabric bolt inventory (PRD §3.2) ---
DEFAULT_REORDER_THRESHOLD = 5

TEST_DEFAULTS = {
    "PRICE_PER_YARD": 5.00,
    "ORIGINAL_YARDS": 50,
    "CLASS_CAPACITY": 5,
    "CLASS_FEE": 20.00,
}
