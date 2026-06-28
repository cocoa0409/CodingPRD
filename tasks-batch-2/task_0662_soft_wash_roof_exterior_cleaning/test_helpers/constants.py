"""Domain thresholds — numeric constants from PRD pricing, dose, and scheduling rules."""

# Chemical dose (PRD §3.2 "The chemical dose ... derived from three inputs").
CHEMICAL_DOSE = {
    "BASE_OZ": {"ROOF_SOFT_WASH": 6, "HOUSE_WASH": 3, "CONCRETE_CLEAN": 4},
    "SOIL_MULT": {"LIGHT": 0.8, "MODERATE": 1.0, "HEAVY": 1.4},
    "MIN_PRIME_OZ": 8.0,
    "MAX_TANK_OZ": 320.0,
}

# Line pricing (PRD §3.2 "The line price is derived ...").
LINE_PRICING = {
    "SURFACE_RATE": {"ROOF": 22, "SIDING": 15, "CONCRETE": 11},   # cents per sqft
    "SERVICE_MULT": {"ROOF_SOFT_WASH": 1.25, "HOUSE_WASH": 1.0, "CONCRETE_CLEAN": 1.1},
    "HEIGHT_STEP": 0.10,   # per story above the first
}

# Travel surcharge tiers (PRD §3.2 "The travel surcharge is a function of the subtotal alone").
TRAVEL_SURCHARGE = {
    "LARGE_JOB_CENTS": 5_000_000,   # >= this => 0 surcharge
    "MID_JOB_CENTS": 1_500_000,     # >= this (and < large) => half flat
    "FLAT_TRAVEL_CENTS": 7_500,
}

# Loyalty discount tiers (PRD §3.8 "The loyalty discount rewards recurring-plan tenure").
LOYALTY_DISCOUNT = {
    "TIER_2_PCT": 0.05,    # visits_generated_count >= 2
    "TIER_5_PCT": 0.10,    # >= 5
    "TIER_10_PCT": 0.15,   # >= 10
}

# Weather (PRD §3.4 "BLOCKED if the wind_mph is at least the maximum safe wind of 35 mph").
WEATHER = {
    "MAX_WIND_MPH": 35,
}

# Technician risk score (PRD §3.11).
RISK_SCORE = {
    "LOAD_RISK": 20,
    "UNINSURED_RISK": 50,
    "DECAY": 0.5,
    "RISK_CEILING": 100,
}

# Defaults / fixtures.
DEFAULT_DURATION_MINUTES = 120
DEFAULT_TRAVEL_BUFFER_MINUTES = 30
DEFAULT_LADDER_CERT_MAX_STORIES = 1

# Logical clock default (PRD §2.10).
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"
# A safe "now" used by fixtures that need the clock comfortably before service dates.
FIXTURE_CLOCK_UTC = "2026-04-15T00:00:00Z"

# Generous credit limit so the §3.5 fiscal gate never trips in happy-path fixtures.
HIGH_CREDIT_LIMIT_CENTS = 100_000_000
