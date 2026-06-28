"""Domain thresholds — numeric constants from PRD calculations (Sections 2 & 3)."""

# Studio fee, settlement, tier discount (PRD 3.2, 3.8)
STUDIO_FEE_PER_PAINTER_CENTS = 1000
TIER_DISCOUNT_PCT = {"BRONZE": 0.0, "SILVER": 0.05, "GOLD": 0.10}
POINT_REDEEM_VALUE_CENTS = 1

# Visit points earned (PRD 3.8)
POINTS_PER_CENT_DIVISOR = 100
GOLD_BONUS_THRESHOLD_CENTS = 10000
BONUS_MULTIPLIER = 1.5

# Supplies charge (PRD 3.7)
BULK_QTY_THRESHOLD = 3
BULK_DISCOUNT_PCT = 0.10

# Party deposit (PRD 3.6)
PACKAGE_RATE_CENTS = {"BASIC": 4500, "DELUXE": 8000}
PACKAGE_MIN_GUESTS = {"BASIC": 6, "DELUXE": 10}
DEPOSIT_RATE = 0.25

# Enrollment points earned (PRD 3.10)
LONG_SERIES_THRESHOLD = 6
LONG_SERIES_BONUS = 50

# Member tier thresholds (PRD 3.1)
SILVER_THRESHOLD = 500
GOLD_THRESHOLD = 2000

# Logical clock (PRD 2.4)
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"

# A syntactically-valid UUID that does not resolve to any resource.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
