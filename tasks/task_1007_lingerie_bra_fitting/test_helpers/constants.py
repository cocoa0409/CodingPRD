"""Domain thresholds and constants for the Lingerie & Bra-Fitting Boutique API.

All numeric constants are drawn from the PRD's calculation rules (size recommendation,
pricing, order totals, loyalty, insurance coverage, inventory, scheduling windows).
"""

# ─── Size recommendation ──────────────────────────────────────────────────
CM_PER_INCH = 2.54
CUP_STEP_CM = 2.5
# cup index 1..8 -> letter
CUP_LETTERS = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G", 8: "H"}
UNDERBUST_MIN_CM = 55
UNDERBUST_MAX_CM = 120
BUST_MIN_CM = 60
BUST_MAX_CM = 170

# ─── SKU pricing (extended-size surcharge) ────────────────────────────────
SIZE_SURCHARGE_CENTS = 500
EXTENDED_BAND_MIN = 40
EXTENDED_CUP_MIN_INDEX = 6  # F and larger

# ─── Order totals ─────────────────────────────────────────────────────────
TIER_DISCOUNT_PCT = {"BRONZE": 0.00, "SILVER": 0.05, "GOLD": 0.10}
GIFT_WRAP_FEE_CENTS = 800
SPECIAL_ORDER_FEE_CENTS = 1500

# ─── Loyalty ──────────────────────────────────────────────────────────────
POINTS_DIVISOR_CENTS = 100
TIER_MULTIPLIER = {"BRONZE": 1, "SILVER": 1, "GOLD": 2}
SILVER_THRESHOLD = 1000
GOLD_THRESHOLD = 5000

# ─── Insurance coverage ───────────────────────────────────────────────────
COVERAGE_PCT = 0.80
COVERAGE_CAP_CENTS = 50000

# ─── Inventory ────────────────────────────────────────────────────────────
LOW_STOCK_THRESHOLD = 3

# ─── Scheduling ───────────────────────────────────────────────────────────
FITTER_BUFFER_MIN = 15

# ─── Temporal windows ─────────────────────────────────────────────────────
REPLACEMENT_INTERVAL_MONTHS = 6
EXCHANGE_WINDOW_DAYS = 30

# ─── Logical clock ────────────────────────────────────────────────────────
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

# Convenience aggregate mirroring the example-pattern THRESHOLDS dict.
THRESHOLDS = {
    "SIZE_SURCHARGE_CENTS": SIZE_SURCHARGE_CENTS,
    "EXTENDED_BAND_MIN": EXTENDED_BAND_MIN,
    "EXTENDED_CUP_MIN_INDEX": EXTENDED_CUP_MIN_INDEX,
    "GIFT_WRAP_FEE_CENTS": GIFT_WRAP_FEE_CENTS,
    "SPECIAL_ORDER_FEE_CENTS": SPECIAL_ORDER_FEE_CENTS,
    "POINTS_DIVISOR_CENTS": POINTS_DIVISOR_CENTS,
    "SILVER_THRESHOLD": SILVER_THRESHOLD,
    "GOLD_THRESHOLD": GOLD_THRESHOLD,
    "COVERAGE_PCT": COVERAGE_PCT,
    "COVERAGE_CAP_CENTS": COVERAGE_CAP_CENTS,
    "LOW_STOCK_THRESHOLD": LOW_STOCK_THRESHOLD,
    "FITTER_BUFFER_MIN": FITTER_BUFFER_MIN,
    "REPLACEMENT_INTERVAL_MONTHS": REPLACEMENT_INTERVAL_MONTHS,
    "EXCHANGE_WINDOW_DAYS": EXCHANGE_WINDOW_DAYS,
}
