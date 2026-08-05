"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Delinquency / lien thresholds (PRD §3.6, §3.9)
DELINQUENCY_GRACE_DAYS = 21
LIEN_MIN_ARREARS_CENTS = 10000

# Bill due-date offset (PRD §3.3)
NET_DUE_DAYS = 20

# Test water schedule tiers (PRD §3.3): cents per 1000 gallons.
WATER_TIERS = [
    {"upper_bound_units": 6000, "rate_cents_per_1000": 315},
    {"upper_bound_units": 12000, "rate_cents_per_1000": 500},
    {"upper_bound_units": None, "rate_cents_per_1000": 800},
]
WATER_TIER1_RATE = 315

# Test electric schedule tiers (PRD §3.3): cents per 1000 kWh.
ELECTRIC_TIERS = [
    {"upper_bound_units": 500, "rate_cents_per_1000": 12000},
    {"upper_bound_units": None, "rate_cents_per_1000": 18000},
]

# Test sewer schedule (PRD §3.3, §3.8)
SEWER_RATE = 250
SEWER_CAP_UNITS = 10000

# Common fixed charge used across the test rate schedules
WATER_FIXED_CHARGE_CENTS = 1000
SEWER_FIXED_CHARGE_CENTS = 800

# Logical-clock startup default (PRD §2.6)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
