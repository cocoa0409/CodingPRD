"""Domain thresholds and constants from PRD pricing/charge calculations."""

# Flat delivery fee keyed by catalog category (PRD §3.4).
DELIVERY_FEE_BY_CATEGORY_CENTS = {
    "HAND_TOOL": 0,
    "POWER_TOOL": 2500,
    "HEAVY_EQUIPMENT": 12000,
}

# Block sizes used by the tiered rental charge (PRD §3.8).
WEEK_DAYS = 7
FOUR_WEEK_DAYS = 28

# Canonical rate-card numbers reused across the design indices.
RATE_CARD = {
    "daily_rate_cents": 4000,
    "weekly_rate_cents": 20000,
    "four_week_rate_cents": 60000,
    "deposit_cents": 50000,
    "damage_waiver_daily_cents": 1500,
    "fuel_refill_cents_per_liter": 200,
    "cleaning_fee_cents": 8000,
    "late_fee_multiplier": 1.5,
}

# A syntactically valid UUID guaranteed not to resolve to any created resource.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
