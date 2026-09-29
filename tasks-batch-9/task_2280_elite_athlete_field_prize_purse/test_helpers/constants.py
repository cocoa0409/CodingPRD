"""Domain thresholds and rates stated by the PRD."""

# --------------------------------------------------------------------------
# The logical race clock (PRD §2.4)
# --------------------------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_START_STAMP = "2026-08-01T00:00:00.000Z"

# --------------------------------------------------------------------------
# Guaranteed valuation components (PRD §3.4)
# --------------------------------------------------------------------------
AIR_ALLOWANCE_CENTS = {
    "ECONOMY": 120_000,
    "PREMIUM_ECONOMY": 260_000,
    "BUSINESS": 540_000,
}
HOTEL_NIGHTLY_CENTS = 32_000
HOTEL_NIGHTS_CAP = 7
GROUND_TRANSPORT_CENTS = 18_000


def guaranteed_valuation_cents(appearance_fee_cents, air_class, hotel_nights,
                               ground_transport):
    """Guaranteed valuation of a package (PRD §3.4).

    The hotel night count is capped at seven nights before the nightly rate is
    multiplied.
    """
    air = AIR_ALLOWANCE_CENTS[air_class]
    hotel = min(hotel_nights, HOTEL_NIGHTS_CAP) * HOTEL_NIGHTLY_CENTS
    ground = GROUND_TRANSPORT_CENTS if ground_transport else 0
    return appearance_fee_cents + air + hotel + ground


# --------------------------------------------------------------------------
# Withholding (PRD §3.8)
# --------------------------------------------------------------------------
DOMESTIC_TAX_RESIDENCY = "USA"
STATUTORY_WITHHOLDING_BPS = 3_000
PER_AWARD_DE_MINIMIS_CENTS = 60_000
AGGREGATED_DE_MINIMIS_CENTS = 150_000
MAX_TREATY_WITHHOLDING_BPS = 3_000

# --------------------------------------------------------------------------
# Bonuses (PRD §3.8)
# --------------------------------------------------------------------------
WHEELCHAIR_TIME_BONUS_SCALE_BPS = 7_500

# --------------------------------------------------------------------------
# Elite services (PRD §3.5)
# --------------------------------------------------------------------------
STATION_KM_MARKS = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]
MAX_TABLE_POSITION = 40
MIN_TABLE_POSITION = 1
MAX_BOTTLE_COUNT = 3
MAX_PACING_KM = 32.0
MIN_TARGET_PACE_SECONDS_PER_KM = 120
MAX_TARGET_PACE_SECONDS_PER_KM = 400

# --------------------------------------------------------------------------
# Anti-doping (PRD §3.5, §3.6)
# --------------------------------------------------------------------------
MISSED_TEST_LOOKBACK_DAYS = 365
MISSED_TEST_LIMIT = 2
TESTING_FREQUENCY_WINDOW_DAYS = 7
MAX_TESTS_PER_FREQUENCY_WINDOW = 2

# --------------------------------------------------------------------------
# Edition policy dials and their declared defaults (PRD §3.1, §3.2)
# --------------------------------------------------------------------------
DEFAULT_OFFER_RESPONSE_DAYS = 14
DEFAULT_MAX_NEGOTIATION_ROUNDS = 3
DEFAULT_MASTERS_MIN_AGE = 40
DEFAULT_WINDOW_MONTHS = 24
DEFAULT_REQUIRES_CHIP_TIMING = True
DEFAULT_COMMISSION_BPS = 1_500

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Convenient defaults for building test scenarios
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "RACE_DATE": "2026-11-01",
    "APPEARANCE_BUDGET_CENTS": 10_000_000,
    "TOTAL_PURSE_CENTS": 10_000_000,
    "BONUS_POOL_CAP_CENTS": 10_000_000,
    "MAX_QUALIFYING_SECONDS": 8_100,
    "BIB_RANGE_START": 11,
    "BIB_RANGE_END": 99,
}
