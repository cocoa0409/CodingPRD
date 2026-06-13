"""Domain thresholds and canonical config values used across tests.

These mirror numeric constants stated in the PRD's pricing, ETA, and
service-fee descriptions, plus the canonical "DT" zone configuration used
throughout the test suite.
"""

# Fixed numeric constants from the PRD calculations.
ETA_MINUTES_PER_KM = 3          # PRD §3.5: route_distance_km * three minutes per kilometer
BPS_DENOMINATOR = 10000         # PRD §3.4: service fee divided by 10000

# Canonical "DT" zone configuration used by most fixtures (cents unless noted).
ZONE_DT = {
    "name": "DT",
    "base_delivery_fee_cents": 300,
    "per_km_fee_cents": 120,
    "small_order_threshold_cents": 1500,
    "small_order_fee_cents": 200,
    "delivery_fee_cap_cents": 2000,
    "dasher_min_guarantee_cents": 700,
    "dasher_per_km_pay_cents": 100,
    "dasher_base_pay_cents": 250,
    "service_fee_bps": 850,
    "surge_tier_1_demand": 5,
    "surge_tier_2_demand": 10,
    "surge_multiplier_tier_0": 1.0,
    "surge_multiplier_tier_1": 1.25,
    "surge_multiplier_tier_2": 1.6,
}

# Canonical restaurant defaults: route_distance_km=4 gives
#   raw distance fee = 300 + 120*4 = 780
#   dasher base      = 250 + 100*4 = 650
ROUTE_DISTANCE_KM = 4
PREP_MINUTES = 15
