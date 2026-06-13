"""Domain thresholds — numeric constants from the PRD's pricing and capacity rules."""

# Grams per kilogram — base rate is base_price_cents_per_kg / 1000 (PRD §3.4).
G_PER_KG = 1000

# Holiday deposit is one quarter of the estimated total (PRD §3.6).
HOLIDAY_DEPOSIT_RATE = 0.25

# A whole animal is 4 quarter-units (PRD §3.7).
WHOLE_UNITS = 4

# Standard PricingPolicy payload used across most fixtures. Values chosen so the
# design-index expected numbers reproduce exactly:
#   whole-cut shrink 0.04, grind shrink 0.10, preferred 0.10, wholesale 0.20,
#   bulk threshold 5000g, bulk extra 0.05.
DEFAULT_PRICING_POLICY = {
    "shrink_pct_whole_cut": 0.04,
    "shrink_pct_grind": 0.10,
    "preferred_discount_pct": 0.10,
    "wholesale_discount_pct": 0.20,
    "bulk_threshold_g": 5000,
    "bulk_extra_discount_pct": 0.05,
}

# A safe temperature band used for most lockers ([0, 4] Celsius).
DEFAULT_LOCKER_BAND = {"min_temp_c": 0, "max_temp_c": 4}
