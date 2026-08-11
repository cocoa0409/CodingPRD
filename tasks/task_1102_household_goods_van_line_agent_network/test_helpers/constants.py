"""Domain thresholds — numeric constants stated in the PRD narratives."""

# PRD section 2.5: logical clock startup default.
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

# PRD section 2.6: hundredweight conversion.
CWT_LBS = 100

# PRD section 3.3: estimate validity window.
ESTIMATE_VALIDITY_DAYS = 30

# PRD section 3.3: valuation premium constants.
FVP_RATE_PER_100_CENTS = 85
DEDUCTIBLE_FACTOR = {0: 1.00, 25000: 0.85, 50000: 0.70}

# PRD section 3.4: delivery spread window table (min-inclusive, max-exclusive;
# final band inclusive).
SPREAD_TABLE = [
    {"min_miles": 0, "max_miles": 500, "transit_days": 2, "spread_days": 2},
    {"min_miles": 500, "max_miles": 1500, "transit_days": 4, "spread_days": 3},
    {"min_miles": 1500, "max_miles": 2500, "transit_days": 6, "spread_days": 4},
    {"min_miles": 2500, "max_miles": 999999, "transit_days": 8, "spread_days": 5},
]

# PRD section 3.5: storage-in-transit permanent-conversion cap.
SIT_MAX_DAYS = 180

# PRD section 3.6: crew overtime rule.
OT_THRESHOLD_HOURS = 8
OT_MULTIPLIER = 1.5

# PRD section 3.7: federal 110% collection rule.
NON_BINDING_CAP_PCT = 1.10

# PRD section 3.8: revenue waterfall constants.
ROLE_BASE_PCT = {"BOOKING": 0.10, "ORIGIN": 0.20, "HAULING": 0.54, "DESTINATION": 0.10}
TIER_BONUS = {"STANDARD": 0.00, "PREFERRED": 0.01, "PREMIER": 0.02}
VAN_LINE_FLOOR_PCT = 0.04

# PRD section 3.9: claims and arbitration program constants.
RELEASED_VALUE_CENTS_PER_LB = 60
MAX_CLAIM_ROUNDS = 3
CLAIM_WINDOW_DAYS = 270
MEDIATION_COOLING_OFF_DAYS = 14
ARBITRATION_FILING_FEE_CENTS = 25000

# Test-default tariff shapes used by the composite fixtures.
DEFAULT_TARIFF_BANDS = [
    {"min_miles": 0, "max_miles": 500, "rate_multiplier": 1.0},
    {"min_miles": 500, "max_miles": 1500, "rate_multiplier": 1.2},
    {"min_miles": 1500, "max_miles": 2500, "rate_multiplier": 1.4},
    {"min_miles": 2500, "max_miles": 999999, "rate_multiplier": 1.6},
]
SIMPLE_TARIFF_BANDS = [
    {"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0},
]

TEST_DEFAULTS = {
    "BASE_RATE_CENTS_PER_CWT": 4500,
    "FUEL_SURCHARGE_PCT": 0.10,
    "SIT_DAILY_RATE_CENTS_PER_CWT": 250,
    "HOURLY_LABOR_RATE_CENTS": 4000,
    "PICKUP_DATE": "2026-06-10T00:00:00Z",
    "TARE_WEIGHT_LBS": 14000,
    "ESTIMATED_WEIGHT_LBS": 8000,
    "MILEAGE": 1200,
}
