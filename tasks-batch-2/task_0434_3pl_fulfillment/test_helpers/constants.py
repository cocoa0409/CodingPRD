"""Domain thresholds — numeric constants from the 3PL fulfillment PRD calculations."""

# Cartonization box inner volumes (PRD §3.6), in cubic centimetres.
CARTON_INNER_CC = {
    "SMALL": 1000,
    "MEDIUM": 5000,
    "LARGE": 20000,
}

# Carrier rate cards (PRD §3.7), in integer cents.
CARRIER_RATES = {
    "GROUND_ECONOMY": {"base_cents": 300, "per_zone_cents": 50, "per_carton_cents": 100},
    "GROUND_PLUS": {"base_cents": 500, "per_zone_cents": 40, "per_carton_cents": 120},
    "AIR_EXPRESS": {"base_cents": 1200, "per_zone_cents": 80, "per_carton_cents": 150},
}

# Carrier precedence used as the tie-break order (PRD §3.7).
CARRIER_PRECEDENCE = ["GROUND_ECONOMY", "GROUND_PLUS", "AIR_EXPRESS"]

# carrier_discount_bps is constrained 0..10000 inclusive (PRD §3.1).
CARRIER_DISCOUNT_BPS_MIN = 0
CARRIER_DISCOUNT_BPS_MAX = 10000

# Storage sweep minimum days (PRD §3.11).
MIN_STORAGE_DAYS = 1

# ship_to_zone is constrained 1..8 inclusive (PRD §3.3).
ZONE_MIN = 1
ZONE_MAX = 8

# Default rate-card values used by factories.
TEST_DEFAULTS = {
    "STORAGE_RATE_PER_PALLET_CENTS": 1000,
    "HANDLING_RATE_PER_ORDER_CENTS": 500,
    "HANDLING_RATE_PER_EXTRA_UNIT_CENTS": 50,
    "HANDLING_SURCHARGE_PER_EXTRA_CARTON_CENTS": 200,
    "UNIT_VOLUME_CC": 400,
    "LARGE_BIN_CAPACITY_CC": 100000,
}
