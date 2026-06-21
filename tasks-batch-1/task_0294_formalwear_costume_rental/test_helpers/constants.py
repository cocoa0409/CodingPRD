"""Domain thresholds — numeric constants from the PRD's pricing, settlement,
and sizing rules."""

# Tiered volume discount on the per-rental-day rate (PRD §3.4).
PRICING = {
    "TIER1_MAX_DAYS": 3,        # 1..3 days -> multiplier 1.00
    "TIER2_MAX_DAYS": 7,        # 4..7 days -> multiplier 0.90
    "TIER1_MULTIPLIER": 1.00,
    "TIER2_MULTIPLIER": 0.90,
    "TIER3_MULTIPLIER": 0.80,   # 8+ days
}

# Settlement / damage constants (PRD §3.7).
SETTLEMENT = {
    "DAMAGE_PCT": 0.60,         # DAMAGED damage fee = 60% of replacement value
    "WAIVER_CAP_CENTS": 30000,  # damage waiver absorbs up to this much damage fee
    "MAX_STRIKES": 2,           # auto-retire at 2+ damage strikes
}

# Size chart on chest_cm (half-open buckets [lower, upper)) (PRD §3.2).
SIZE_CHART = {
    "XS_MAX": 86,
    "S_MAX": 96,
    "M_MAX": 106,
    "L_MAX": 116,
    "XL_MAX": 126,
}

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Catalog values reused across fixtures (so cents math in tests stays exact).
CATALOG_DEFAULTS = {
    "daily_rate_cents": 5000,
    "deposit_cents": 20000,
    "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200,
    "cleaning_buffer_days": 2,
    "late_fee_daily_rate_cents": 2000,
}
