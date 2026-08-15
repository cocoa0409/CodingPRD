"""Domain thresholds and catalog constants from the PRD (§2.5, §3.2, §3.5, §3.7-§3.9)."""

# PRD §2.5 trailer catalog: type -> (max_payload_lbs, deck_height_in, cost_per_mile_cents)
TRAILER_CATALOG = {
    "FLATBED": {"max_payload_lbs": 48000, "deck_height_in": 60, "cost_per_mile_cents": 350},
    "STEP_DECK": {"max_payload_lbs": 46000, "deck_height_in": 42, "cost_per_mile_cents": 400},
    "RGN_LOWBOY": {"max_payload_lbs": 90000, "deck_height_in": 24, "cost_per_mile_cents": 550},
    "EXTENDABLE_DOUBLE_DROP": {"max_payload_lbs": 150000, "deck_height_in": 22, "cost_per_mile_cents": 700},
}

# PRD §2.5 legal baselines
LEGAL_WIDTH_IN = 102
LEGAL_HEIGHT_IN = 162
LEGAL_LENGTH_IN = 636
LEGAL_GROSS_LBS = 80000
SUPERLOAD_WEIGHT_LBS = 150000
SUPERLOAD_WIDTH_IN = 192
PER_AXLE_LIMIT_LBS = 20000
MIN_AXLES = 2

# PRD §2.5 / §3.3 survey safety margin
BRIDGE_SAFETY_MARGIN_IN = 6

# PRD §3.2 escort thresholds
ESCORT_WIDTH_TWO_IN = 168
ESCORT_WIDTH_ONE_IN = 144
POLE_HEIGHT_IN = 192

# PRD §3.5 permit fee bases: state -> permit_type -> cents
STATE_BASE_CENTS = {
    "CA": {"OVERSIZE": 9000, "OVERWEIGHT": 15000, "SUPERLOAD": 50000},
    "NV": {"OVERSIZE": 7000, "OVERWEIGHT": 12000, "SUPERLOAD": 40000},
    "AZ": {"OVERSIZE": 8000, "OVERWEIGHT": 13000, "SUPERLOAD": 45000},
    "TX": {"OVERSIZE": 10000, "OVERWEIGHT": 16000, "SUPERLOAD": 55000},
    "OR": {"OVERSIZE": 8500, "OVERWEIGHT": 14000, "SUPERLOAD": 48000},
}

# PRD §3.5 weight surcharge marginal tiers (excess lbs over 80000)
WEIGHT_TIER1_LBS = 20000
WEIGHT_TIER1_CENTS_PER_LB = 1
WEIGHT_TIER2_LBS = 30000
WEIGHT_TIER2_CENTS_PER_LB = 2
WEIGHT_TIER3_CENTS_PER_LB = 4

# PRD §3.5 width surcharge flat brackets (highest applicable only)
WIDTH_BRACKET_GT_192 = 10000
WIDTH_BRACKET_GT_168 = 5000
WIDTH_BRACKET_GT_144 = 2500

# PRD §3.7 standby billing
FREE_MINUTES = 120
PREMIUM_AFTER_BILLABLE_MINUTES = 360
STANDBY_RATE_CENTS_PER_HOUR = 17500
STANDBY_PREMIUM_CENTS_PER_HOUR = 26250

# PRD §2.8 curfew: UTC hour in [5, 21)
CURFEW_START_HOUR = 5
CURFEW_END_HOUR = 21

# PRD §3.8 overweight tolerance and fine tiers
OVERWEIGHT_TOLERANCE_NUM = 103
OVERWEIGHT_TOLERANCE_DEN = 100
FINE_TIER1_LBS = 2000
FINE_TIER1_CENTS_PER_LB = 25
FINE_TIER2_LBS = 3000
FINE_TIER2_CENTS_PER_LB = 50
FINE_TIER3_CENTS_PER_LB = 100

# PRD §3.9 fuel surcharge
FUEL_TIER_THRESHOLD_CENTS = 5000000
FUEL_PCT_HIGH = 0.12
FUEL_PCT_LOW = 0.08

# PRD §2.8 default logical clock instant
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Shared travel window used by fixtures (inside curfew-compatible dates)
TRAVEL_WINDOW_START = "2026-08-10T00:00:00Z"
TRAVEL_WINDOW_END = "2026-08-20T00:00:00Z"
DEPART_CLOCK_ISO = "2026-08-12T10:00:00Z"
