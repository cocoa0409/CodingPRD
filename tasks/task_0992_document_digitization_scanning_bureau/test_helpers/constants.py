"""Domain thresholds and defaults used by the PRD calculations."""

# Logical clock startup default per PRD section 2.5.
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Pricing constants per PRD section 3.6.
STANDARD_PAGE_RATE_USD = 0.45
VOLUME_PAGE_RATE_USD = 0.30

# Indexing minimum OCR confidence per PRD section 3.5.
MIN_OCR_CONFIDENCE = 70

# Rush admission limit per PRD section 3.2.
RUSH_ADMISSION_LIMIT = 3

# Rejection allowance per PRD section 3.6: max(1, floor(0.10 * N)).
REJECT_FRACTION_NUM = 1
REJECT_FRACTION_DEN = 10

# Defaults used by factories.
TEST_DEFAULTS = {
    "RUSH_MULTIPLIER": 1.75,
    "STORAGE_FREE_DAYS": 10,
    "STORAGE_DAILY_RATE_CENTS": 55,
    "RETENTION_DAYS": 30,
    "MAX_BOXES_PER_BATCH": 5,
    "SCANNER_CAPACITY": 500,
    "SHELF_CAPACITY_GRAMS": 2000,
}
