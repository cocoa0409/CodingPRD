"""Domain thresholds — numeric constants from the PRD pricing/turnaround rules."""

# Finish surcharge added to base_unit_price_cents (PRD 3.4).
FINISH_SURCHARGE_CENTS = {
    "MATTE": 0,
    "GLOSSY": 300,
    "LINEN": 700,
    "LAY_FLAT": 1200,
    "METAL": 2500,
}

# Volume-discount tiers: highest min_qty <= quantity wins (average rate). (PRD 3.4)
VOLUME_TIERS = [
    (1, 0.00),
    (10, 0.05),
    (25, 0.12),
    (50, 0.20),
]

# Base shipping charge by method (PRD 3.4).
SHIPPING_CENTS = {"STANDARD": 799, "EXPRESS": 1999}

# Transit days by method (PRD 3.4).
METHOD_TRANSIT_DAYS = {"STANDARD": 5, "EXPRESS": 2}

# Restocking fee fraction applied to subtotal on CARD refunds (PRD 3.7).
RESTOCK_PCT = 0.10

# Promo-window buffer in calendar days (PRD 3.8).
PROMO_WINDOW_BUFFER_DAYS = 2

# Default per-day production capacity when no surge window governs (PRD 3.5).
DEFAULT_DAILY_CAPACITY = 100000

# Default template DPI floor when min_dpi omitted (PRD 3.1).
DEFAULT_MIN_DPI = 150

# Logical clock default at startup (PRD 2.6).
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-03-01"
