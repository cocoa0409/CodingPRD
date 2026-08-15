"""Domain thresholds — numeric constants from PRD calculation rules."""

# De-identification payer floor for AGGREGATE_ONLY inclusion and MRF validation
DEIDENTIFICATION_MIN_PAYERS = 3

# Shoppable bundle discount (ten percent, floored per ancillary item)
BUNDLE_DISCOUNT_PCT = 0.10

# Civil monetary penalty accrual rates (cents per elapsed day)
SIMPLE_DAILY_CENTS = 30000
TIER1_MAX_BEDS = 30
TIER1_DAILY_CENTS = 10000
TIER2_MAX_BEDS = 199
TIER2_DAILY_CENTS = 20000
TIER3_DAILY_CENTS = 40000

# CMS certification count floors (facility defaults)
CMS_DEFAULT_TOTAL_MIN = 300
CMS_DEFAULT_MANDATED_MIN = 70
DEFAULT_MIN_RECORDS_PER_CYCLE = 1

# Logical clock startup default (PRD section 2.5)
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"
SECONDS_PER_DAY = 86400

# Common windows used across setups
CONTRACT_WINDOW = ("2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z")
ANNUAL_2026 = ("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
AUGUST_2026 = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
SEPTEMBER_2026 = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
