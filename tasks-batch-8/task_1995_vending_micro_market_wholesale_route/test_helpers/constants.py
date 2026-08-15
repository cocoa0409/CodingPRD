"""Domain thresholds and logical-clock landmarks from the PRD."""

# Calculation constants (PRD §3.3 cull, §3.6 cashless fee, §3.7 claim tiers).
CULL_MIN_UNITS_4WK = 2
CULL_WINDOW_DAYS = 28
CASHLESS_FEE_BPS = 275          # 2.75% cashless processing fee (PRD §3.6)
CLAIM_WINDOW_DAYS = 30          # post-expiration claim window (PRD §3.7)
SHORT_DATE_DAYS = 14            # 50% tier ceiling (PRD §3.7)
DEEP_SHORT_DATE_DAYS = 7        # 75% tier ceiling (PRD §3.7)

# Logical clock (PRD §2.5): startup default is exactly 2026-08-01T00:00:00Z,
# a Saturday. Dates below are aligned to that default.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"
NEXT_MONDAY = "2026-08-03"      # first Monday after the default logical date
NEXT_TUESDAY = "2026-08-04"
ADVANCED_CLOCK_ISO = "2026-08-10T00:00:00Z"
ADVANCED_MONDAY = "2026-08-10"

TEST_DEFAULTS = {
    "CASE_PACK_QTY": 10,
    "BASE_PRICE_CENTS": 1000,
    "COST_CENTS": 600,
    "VEND_PRICE_CENTS": 150,
    "DAILY_CASE_CAPACITY": 100,
}
