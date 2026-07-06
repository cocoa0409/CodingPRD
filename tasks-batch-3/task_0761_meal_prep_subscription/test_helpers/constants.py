"""Domain thresholds — numeric constants from the PRD calculation rules."""

# Free-shipping threshold: shipping is waived when meal count >= 12 (PRD §3.5).
FREE_SHIP_MIN_MEALS = 12

# First-box referee discount rate (PRD §3.5 / §2.5): 15 percent, per-line round-half-up then sum.
REFEREE_DISCOUNT_PCT = 0.15

# Referral reward tiers (PRD §3.6).
REFERRAL_BASE_CENTS = 2000
PREMIUM_BONUS_CENTS = 1500
PREMIUM_MIN_MEALS = 12

# Kitchen-line cleaning buffer in minutes (PRD §3.1).
LINE_BUFFER_MINUTES = 60

# The logical clock's startup default (PRD §2.6).
CLOCK_START_UTC = "2026-03-01T00:00:00Z"

# Canonical fixture literals reused across the suite.
ZONE_WEST = {
    "zone_code": "WEST",
    "name": "West",
    "requires_cold_pack": True,
    "base_shipping_fee_cents": 1000,
    "cold_pack_fee_cents": 500,
    "order_lead_days": 4,
    "cutoff_time_utc": "18:00",
}
PLAN_PRO = {"plan_code": "PRO", "name": "Pro", "meals_per_week": 12, "price_per_meal_cents": 1099}
PLAN_STARTER = {"plan_code": "STARTER", "name": "Starter", "meals_per_week": 6, "price_per_meal_cents": 1299}

# Delivery 2026-03-16 in WEST (lead 4, cutoff 18:00) -> cutoff_at 2026-03-12T18:00:00Z.
DELIVERY_DATE = "2026-03-16"
CUTOFF_AT = "2026-03-12T18:00:00Z"
