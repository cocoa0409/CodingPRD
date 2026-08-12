"""Domain thresholds — numeric constants from PRD §3 calculations."""

# Cord-equivalent factors per product kind (PRD §3.6)
CORD_EQUIVALENT_PER_UNIT = {
    "CORD": 1.0,
    "HALF_CORD": 0.5,
    "PELLET_TON": 0.8,
    "PELLET_BAG": 0.016,
}

# Seasoned-grade price multipliers (PRD §3.6)
GRADE_MULTIPLIER = {
    "GREEN": 0.75,
    "SEMI_SEASONED": 1.00,
    "KILN_DRIED": 1.35,
}

# Marginal volume tiers (PRD §3.6)
VOLUME_TIERS = [
    (0.0, 2.0, 0.00),
    (2.0, 4.0, 0.04),
    (4.0, 8.0, 0.07),
    (8.0, float("inf"), 0.11),
]

# Loyalty tiers (PRD §3.1, §3.6)
LOYALTY_SILVER_THRESHOLD_CE = 4.0
LOYALTY_GOLD_THRESHOLD_CE = 10.0
LOYALTY_DISCOUNT_RATE = {"STANDARD": 0.00, "SILVER": 0.02, "GOLD": 0.04}

# Winter peak surcharge (PRD §3.6)
PEAK_WINDOW_START = "12-15"
PEAK_WINDOW_END = "02-15"
SEASONAL_SURCHARGE_RATE = {"STANDARD": 0.12, "SILVER": 0.08, "GOLD": 0.00}

# Stacking fee (PRD §3.6)
STACKING_FLAT_FEE_CENTS = 3500
STACKING_PER_CORD_CENTS = 1200

# Delivery fee zones (PRD §3.6)
ZONE_A_FEE_CENTS = 4500   # matched prefix length >= 5
ZONE_B_FEE_CENTS = 6500   # matched prefix length 3-4
ZONE_C_FEE_CENTS = 9500   # matched prefix length 1-2
BULK_THRESHOLD_1_CE = 4.0
BULK_THRESHOLD_2_CE = 8.0
BULK_SURCHARGE_CENTS = 1500

# Cancellation fee (PRD §3.8)
CANCELLATION_FEE_RATE = 0.10
LATE_FEE_THRESHOLD_HOURS = 72

# Subscription clawback (PRD §3.3)
CLAWBACK_ADMIN_FEE_CENTS = 5000

# Shortfall penalty (PRD §3.9)
SHORTFALL_RATE = 0.20

# Invoice due date offset (PRD §3.8)
INVOICE_DUE_DATE_OFFSET_DAYS = 7

# Logical clock startup default (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 40000,
    "MOISTURE_CEILING_KILN": 20.0,
}
