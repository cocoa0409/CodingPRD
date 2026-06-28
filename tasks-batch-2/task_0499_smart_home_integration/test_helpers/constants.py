"""Domain thresholds — numeric constants from PRD calculations."""

# Volume discount tiers (cents) and rates (PRD §3.2)
VOLUME_T1_CENTS = 500_000
VOLUME_T2_CENTS = 2_000_000
VOLUME_T1_RATE = 0.05
VOLUME_T2_RATE = 0.10
LOYALTY_COMMERCIAL_RATE = 0.02
DISCOUNT_CAP_RATE = 0.12

# Tax rates (PRD §3.2)
RESIDENTIAL_TAX_RATE = 0.0825
COMMERCIAL_TAX_RATE = 0.00

# Region x billing_tier labor rate matrix in cents per hour (PRD §3.2)
LABOR_RATE_CENTS = {
    "RESIDENTIAL": {"NORTH": 12000, "SOUTH": 10000, "EAST": 13000, "WEST": 11000},
    "COMMERCIAL": {"NORTH": 15000, "SOUTH": 13000, "EAST": 16000, "WEST": 14000},
}

# Contract balance floor (PRD §3.9)
CONTRACT_FLOOR_CENTS = 0

# Crew daily visit cap default (PRD §3.7)
DEFAULT_DAILY_CAP = 2

# Default device rack units (PRD §3.5)
DEFAULT_RACK_UNITS = 1

# The server logical clock startup default (PRD §2.10)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Common test values
TEST_DEFAULTS = {
    "SUBNET_24": "10.20.0.0/24",
    "SUBNET_30": "10.20.0.0/30",
    "RACK_UNITS_TOTAL": 10,
}
