"""Domain thresholds — numeric constants from the PRD's charge, shipping, sizing,
confidence, cadence, and inventory rules."""

# Charge computation (PRD §3.5, §3.6, §2.8)
STYLING_FEE_CENTS = 2000
BUY_THE_LOOK_DISCOUNT_PCT = 0.25
TAX_RATE = {"CA": 0.0725, "NY": 0.04, "OR": 0.0}

# Shipping (PRD §3.6)
SHIPPING_FEE_CENTS = 795
FREE_SHIP_NET_THRESHOLD_CENTS = 7500

# Try-at-home window (PRD §3.5)
TRY_AT_HOME_DAYS = 3

# Fix item-count bounds (PRD §3.4)
MIN_ITEMS = 3
MAX_ITEMS = 5

# Cadence intervals in days (PRD §3.2)
CADENCE_DAYS = {
    "EVERY_2_WEEKS": 14,
    "MONTHLY": 30,
    "EVERY_2_MONTHS": 60,
    "QUARTERLY": 90,
}

# Learned sizing (PRD §3.8)
DECAY = 0.5
SIZE_ADJUSTMENT = {
    "TOO_SMALL": 1.0,
    "SLIGHTLY_SMALL": 0.5,
    "PERFECT": 0.0,
    "SLIGHTLY_LARGE": -0.5,
    "TOO_LARGE": -1.0,
}

# Fit confidence (PRD §3.8)
CONFIDENCE_MATCH = {
    "PERFECT": 1.0,
    "SLIGHTLY_SMALL": 0.6,
    "SLIGHTLY_LARGE": 0.6,
    "TOO_SMALL": 0.0,
    "TOO_LARGE": 0.0,
}

# Logical clock default at server startup (PRD §2.9)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# A syntactically valid UUID that resolves to no resource.
BOGUS_UUID = "00000000-0000-4000-8000-000000000000"
