"""Domain thresholds — numeric constants from PRD price and guarantee calculations."""

# Per-room soiling multipliers (PRD §3.2 / §3.4).
SOIL_MULT = {
    "LIGHT": 1.0,
    "MODERATE": 1.25,
    "HEAVY": 1.6,
}

# Recurring discount by plan cadence (PRD §3.1 / §3.2).
RECUR_DISCOUNT_PCT = {
    "MONTHLY": 0.15,
    "QUARTERLY": 0.10,
    "SEMIANNUAL": 0.05,
}

# Heavy-soiling escalation at settlement (PRD §3.4).
HEAVY_ESCALATION_COUNT = 3
HEAVY_ESCALATION_CENTS = 4000

# Re-clean guarantee (PRD §3.5).
GUARANTEE_WINDOW_FACTOR = 2
GUARANTEE_GOODWILL_CENTS = 2000

# Default catalog used across most fixtures. STEAM, base 50 cents/sqft,
# dry_time 240 min (guarantee window = 480 min).
CATALOG_DEFAULTS = {
    "service_type": "STEAM",
    "base_rate_cents_per_sqft": 50,
    "stain_addon_cents": 2500,
    "pet_addon_cents": 1800,
    "protectant_cents_per_sqft": 12,
    "move_furniture_flat_cents": 3000,
    "dry_time_minutes": 240,
}
