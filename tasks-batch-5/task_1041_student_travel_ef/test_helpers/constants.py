"""Domain thresholds — numeric constants drawn from the PRD's pricing, refund,
free-spot, deposit, and chaperone-buffer rules."""

# Enrollment pricing (PRD §3.3)
EARLY_BIRD_PCT = 0.10
ADDON_PRICES = {
    "SINGLE_ROOM": 40000,
    "EXCURSION": 12000,
    "STEM_LAB": 8000,
}
INSURANCE_PREMIUMS = {
    "BASIC": 9900,
    "PREMIUM": 19900,
}

# Payment plan (PRD §3.4)
DEFAULT_DEPOSIT_CENTS = 30000

# Refund tiers by whole days before departure (PRD §3.6)
REFUND_PCT_90_PLUS = 1.00
REFUND_PCT_60_89 = 0.75
REFUND_PCT_30_59 = 0.50
REFUND_PCT_UNDER_30 = 0.00

# Free-spot / chaperone ratio (PRD §3.2, §3.8)
DEFAULT_CHAPERONE_RATIO = 6
CHAPERONE_REST_BUFFER_DAYS = 1

# Room capacities by type (PRD §3.8)
ROOM_CAPACITY = {
    "DOUBLE": 2,
    "TRIPLE": 3,
    "QUAD": 4,
}

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# Convenient reference price used across many scenarios
TEST_PRICE_CENTS = 250000
