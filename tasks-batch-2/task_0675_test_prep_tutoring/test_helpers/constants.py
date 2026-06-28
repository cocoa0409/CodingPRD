"""Domain thresholds — numeric constants from PRD calculations."""

# Coupon discount constants (PRD §3.3).
EARLYBIRD_PCT = 0.15
REFER50_FLAT_CENTS = 5000

# Percentile scale (PRD §3.5).
PERCENTILE_SCALE = 100

# Server logical-clock startup default (PRD §2.8).
CLOCK_STARTUP_DEFAULT = "2026-04-01T00:00:00Z"

# Exam scale maxima (PRD §3.1 examples).
SCALE_SAT = 1600
SCALE_ACT = 36
SCALE_MCAT = 528
SCALE_LSAT = 180

# Allowed installment counts (PRD §3.6).
ALLOWED_INSTALLMENT_COUNTS = [1, 2, 3, 4, 6, 12]

# Test default values used by factories/fixtures.
TEST_DEFAULTS = {
    "LIST_PRICE_CENTS": 100000,
    "GUARANTEE_MIN_DELTA": 200,
    "REQUIRED_PRACTICE_TESTS": 1,
    "REQUIRED_ATTENDANCE_PCT": 0.5,
    "MATERIALS_ACCESS_DAYS": 30,
    "SEAT_CAPACITY": 5,
    "TOTAL_SESSIONS": 4,
    "STARTS_AT": "2026-06-01T00:00:00Z",
    "ENDS_AT": "2026-06-30T00:00:00Z",
    "BASE_CLOCK": "2026-05-01T00:00:00Z",
}
