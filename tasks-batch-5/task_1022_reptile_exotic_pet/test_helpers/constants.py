"""Domain thresholds — numeric constants drawn from the PRD's calculations."""

# Regulated surcharge rate by permit class (PRD §3.4).
REGULATED_SURCHARGE_PCT = {
    "NONE": 0.00,
    "CLASS_I": 0.05,
    "CLASS_II": 0.10,
    "CLASS_III": 0.15,
}

# Loyalty discount (final price only) by tier (PRD §3.4).
LOYALTY_DISCOUNT_PCT = {
    "STANDARD": 0.00,
    "SILVER": 0.05,
    "GOLD": 0.10,
}

# Expo discount when sold_at_expo is true (PRD §3.4).
EXPO_DISCOUNT_PCT = 0.08

# Feeder size multiplier for the per-unit shipment price (PRD §3.6).
SIZE_MULT = {
    "SMALL": 1.00,
    "MEDIUM": 1.25,
    "LARGE": 1.50,
}

# Habitat deposit percentage (PRD §3.8).
DEPOSIT_PCT = 0.30

# Minimum PASS health checks before quarantine clearance (PRD §3.2).
MIN_PASS_CHECKS = 2

# Install crew buffer in minutes (PRD §3.8).
INSTALL_BUFFER_MINUTES = 60

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Logical-clock startup default (PRD §2.5).
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"
