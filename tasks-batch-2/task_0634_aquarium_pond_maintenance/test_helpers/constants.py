"""Domain thresholds — numeric constants from PRD calculations."""

# Visit billing (PRD §3.4)
TIER_BASE_CENTS = {"BASIC": 6000, "PLUS": 9000, "PREMIUM": 13000}
TIER_INCLUDED_MINUTES = {"BASIC": 30, "PLUS": 45, "PREMIUM": 60}
TIER_DISCOUNT_RATE = {"BASIC": 0.00, "PLUS": 0.10, "PREMIUM": 0.15}
PER_BLOCK_CENTS = 2000
LABOR_BLOCK_MINUTES = 15
EMERGENCY_SURCHARGE_RATE = 0.25

# Install billing (PRD §3.8)
DEPOSIT_RATE = 0.30

# Bioload (PRD §2.9)
WASTE_FACTOR = {
    "COMMUNITY": 1.0,
    "CICHLID": 1.5,
    "GOLDFISH": 2.0,
    "PREDATOR": 2.5,
    "INVERT": 0.5,
}
OVERSTOCK_THRESHOLD = 100.0

# Logical clock default (PRD §3.11)
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
