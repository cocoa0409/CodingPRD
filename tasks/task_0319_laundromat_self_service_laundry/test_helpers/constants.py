"""Domain thresholds — numeric constants from the PRD's pricing calculations (§2.6, §3)."""

# Basis-points denominator (PRD §2.6: "the basis-points denominator is 10000").
BPS_DENOM = 10000

# Rush surcharge on a WDF order: 2500 basis points = 25% (PRD §3.5).
WDF_RUSH_BPS = 2500

# Plan field defaults stated in PRD §3.1.
PLAN_DEFAULTS = {
    "dry_block_minutes": 8,
    "surge_multiplier_bps": 10000,
    "surge_start_hour_utc": 16,
    "surge_end_hour_utc": 20,
    "wdf_minimum_cents": 1500,
    "reload_bonus_tier1_min_cents": 2000,
    "reload_bonus_tier1_bps": 500,
    "reload_bonus_tier2_min_cents": 5000,
    "reload_bonus_tier2_bps": 1000,
    "loyalty_cents_per_point": 100,
    "loyalty_redeem_threshold_points": 50,
}

# Machine washer default cycle length (PRD §3.2).
DEFAULT_CYCLE_MINUTES = 30

# Pagination bounds (PRD §2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}
