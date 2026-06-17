"""Domain thresholds — numeric constants drawn from the PRD calculation rules
(Sections 2.7, 2.8, and 3). Generic NON_EXISTENT_UUID comes from the framework.
"""

# Visit charge math (PRD §3.4 / §3.5)
AREA_DIVISOR_SQFT = 1000          # area factor divides base_rate*turf_area by 1000
MINUTES_PER_HOUR = 60

# Add-on tiered pricing (PRD §3.6)
ADDON_TIER1_QTY = 10              # first 10 units at full unit price
ADDON_TIER2_QTY = 50             # units 11..50 at the 10% discount
ADDON_DISCOUNT_T2 = 0.10         # 10% off for tier-2 units
ADDON_DISCOUNT_T3 = 0.20         # 20% off for tier-3 units (above 50)

# Storm dispatch charge (PRD §3.8)
STORM_TIER_LIGHT_MAX = 3         # snowfall strictly < 3 -> light tier
STORM_TIER_HEAVY_MAX = 8         # snowfall strictly < 8 -> moderate tier; >= 8 -> heavy
STORM_BASE_LIGHT_CENTS = 15000
STORM_BASE_MODERATE_CENTS = 30000
STORM_BASE_HEAVY_CENTS = 60000
STORM_PRIORITY_SURCHARGE = 0.25  # PRIORITY zone adds 25%

# Invoice tax (PRD §3.10)
TAX_RATE = 0.0825

# Inspection grading thresholds (PRD §3.9)
PASS_THRESHOLD = 85              # score >= 85 -> PASSED
REWORK_FLOOR = 60               # [60, 85) -> REWORK (if rework_count < max) else FAILED
MAX_REWORK = 2                  # max rework loops before forced FAILED

# Reusable test default amounts
TEST_DEFAULTS = {
    "BIG_BUDGET": 100000000,
    "BASE_RATE": 10000,
    "HOURLY_RATE": 6000,
    "TURF_AREA": 5000,
}
