"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3)."""

# Grade multipliers applied to a store-owned copy's list price (PRD §2.5, §3.1).
GRADE_MULTIPLIER = {
    "M": 1.10,
    "NM": 1.00,
    "VG_PLUS": 0.80,
    "VG": 0.60,
    "G": 0.40,
    "F": 0.25,
    "P": 0.15,
}

# Trade-in buy multipliers (PRD §3.6).
BUY_MULTIPLIER = {
    "M": 0.55,
    "NM": 0.50,
    "VG_PLUS": 0.40,
    "VG": 0.30,
    "G": 0.20,
    "F": 0.10,
    "P": 0.05,
}

CREDIT_BONUS_PCT = 0.20  # 20% credit bonus on final CREDIT trade-in value (PRD §3.6)

# Consignment marginal commission tiers (PRD §3.7): (upper_bound_cents_inclusive, rate)
COMMISSION_TIERS = [(5000, 0.30), (20000, 0.20), (99999999, 0.10)]

# Order-total loyalty discount rates by tier (PRD §3.2).
LOYALTY_DISCOUNT_PCT = {"STANDARD": 0.00, "SILVER": 0.05, "GOLD": 0.10}
FREE_SHIP_THRESHOLD_CENTS = 5000  # ONLINE order free ship at/above this subtotal (PRD §3.2)
FLAT_SHIP_CENTS = 599             # flat online shipping below threshold (PRD §3.2)

# Loyalty points multiplier by tier (PRD §3.3).
POINTS_MULTIPLIER = {"STANDARD": 1.0, "SILVER": 1.0, "GOLD": 1.5}

# Loyalty tier lower bounds, inclusive (PRD §3.3).
SILVER_MIN = 100
GOLD_MIN = 500

# Consignment display-slot buffer, in days (PRD §3.7).
CONSIGNMENT_BUFFER_DAYS = 2

# Server logical-clock startup default (PRD §3.10).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"
