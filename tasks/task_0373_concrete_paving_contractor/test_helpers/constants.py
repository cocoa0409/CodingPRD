"""Domain thresholds — numeric constants from PRD calculations (§3)."""

# Cubic-yard math (§3.1)
WASTE_FACTOR = 0.10
CUBIC_FEET_PER_YARD = 27
INCHES_PER_FOOT = 12
TICKET_INCREMENT_CY = 0.25

# Tiered labor pricing (§3.2)
RATE_TIER1 = 9.00   # first 500 sqft
RATE_TIER2 = 7.50   # next 1000 sqft (500..1500)
RATE_TIER3 = 6.00   # beyond 1500 sqft
TIER1_BREAKPOINT = 500
TIER2_BREAKPOINT = 1500
MIX_RATE_PER_CY = 145.00

FINISH_MULT = {"BROOM": 1.00, "EXPOSED_AGGREGATE": 1.20, "STAMPED": 1.35}
REINF_RATE = {"NONE": 0.00, "MESH": 0.60, "REBAR": 1.25}

# Draw waterfall cap (§3.11)
RETAINAGE_PCT = 0.10

# Cure windows in hours (§3.6)
CURE_HOURS = {"STANDARD": 168, "HIGH_EARLY": 72, "FIBER": 168}

# Warranty risk score weights (§3.7)
W_CURE = 30
W_WEATHER = 25
W_CLAIM = 15
W_NO_REINF = 10
WARRANTY_RISK_MIN = 0
WARRANTY_RISK_MAX = 100

# Equipment double-booking cleandown buffer (§3.8)
EQUIPMENT_BUFFER_HOURS = 2

# Weather gate thresholds (§3.5)
WEATHER_TEMP_MIN = 40
WEATHER_TEMP_MAX = 90
WEATHER_PRECIP_MAX = 50
