"""Constants the PRD pins by value: clock defaults, statute-profile defaults,
calculation constants and the canonical statutory timeline used by fixtures.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# StatuteProfile declared defaults (PRD §2.6)
# --------------------------------------------------------------------------
DEFAULT_SIGNATURE_BASIS = "ASSESSED_VALUE"
DEFAULT_SIGNATURE_THRESHOLD_PCT = 50.00
DEFAULT_PROTEST_BASIS = "ASSESSED_VALUE"
DEFAULT_PROTEST_THRESHOLD_PCT = 20.00
DEFAULT_CONTIGUITY_MIN_RATIO = 0.125
DEFAULT_URBAN_DENSITY_MIN_UNITS_PER_ACRE = 2.00
DEFAULT_SUBDIVISION_TEST_MIN_DEVELOPED_RATIO = 0.60
DEFAULT_MIN_QUALIFICATION_INDEX = 60.00
DEFAULT_NOTICE_MIN_DAYS = 30
DEFAULT_HEARING_TO_ORDINANCE_MIN_DAYS = 10
DEFAULT_REQUIRED_SERVICE_TYPES = ["POLICE", "FIRE", "WATER", "SEWER"]
DEFAULT_POLICE_FIRE_TIMELINE_MAX_DAYS = 60
DEFAULT_WATER_SEWER_TIMELINE_MAX_DAYS = 730
DEFAULT_FISCAL_METHOD = "AVERAGE_COST"
DEFAULT_PER_CAPITA_SHARED_REVENUE_CENTS = 12000
DEFAULT_REFERENDUM_REQUIRED_METHODS: list = []
DEFAULT_BOUNDARY_COMMISSION_REQUIRED = False
DEFAULT_DE_ANNEXATION_ALLOWED = True
DEFAULT_DE_ANNEXATION_REFUND_BASIS = "DAILY_PRORATION"
DEFAULT_MSD_ALTERNATIVE_ALLOWED = True
DEFAULT_MSD_COST_RECOVERY_PCT = 0.75
DEFAULT_EFFECTIVE_DATE_RULE = "IMMEDIATE"
DEFAULT_FISCAL_YEAR_END_MONTH_DAY = "12-31"

# --------------------------------------------------------------------------
# Municipality declared defaults (PRD §3.1)
# --------------------------------------------------------------------------
DEFAULT_FISCAL_DEFICIT_TOLERANCE_PCT = 5.00
DEFAULT_HEARING_CHANGEOVER_BUFFER_MINUTES = 30
DEFAULT_UTILITY_OUTSIDE_SURCHARGE_PCT = 0.50

# --------------------------------------------------------------------------
# Other entity defaults
# --------------------------------------------------------------------------
DEFAULT_CONCURRENT_PROJECT_CAPACITY = 1
DEFAULT_CIRCULATION_DAYS = 180
DEFAULT_PROTEST_WINDOW_DAYS = 30
DEFAULT_HORIZON_YEARS = 5
DEFAULT_COMMITTED_ACCOUNT_COUNT = 0
DEFAULT_CASE_TYPE = "ANNEXATION"
DEFAULT_MAX_SERVICE_DISTANCE_MILES = 0

# --------------------------------------------------------------------------
# Territory qualification constants (PRD §3.2)
# --------------------------------------------------------------------------
CONTIGUITY_RAMP_MULTIPLE = 2
URBAN_BONUS = 25.0
DENSITY_PENALTY = 15.0
DISTANCE_FREE_MILES = 3
DISTANCE_PENALTY_PER_MILE = 10.0

# --------------------------------------------------------------------------
# Petition sufficiency (PRD §3.3)
# --------------------------------------------------------------------------
OWNER_100_REQUIRED_PCT = 100.00

# --------------------------------------------------------------------------
# Fiscal impact projection (PRD §3.4)
# --------------------------------------------------------------------------
OVERHEAD_TIER_1_CEILING_CENTS = 5_000_000
OVERHEAD_TIER_2_CEILING_CENTS = 25_000_000
OVERHEAD_TIER_1_PCT = 0.12
OVERHEAD_TIER_2_PCT = 0.09
OVERHEAD_TIER_3_PCT = 0.06
MONTHS_PER_YEAR = 12

# --------------------------------------------------------------------------
# Proration and refunds (PRD §3.8, §3.9)
# --------------------------------------------------------------------------
FISCAL_YEAR_DAYS = 365
QUARTERS_PER_YEAR = 4

# --------------------------------------------------------------------------
# Plan readiness (PRD §3.5)
# --------------------------------------------------------------------------
SERVICE_TYPE_ORDER = ["POLICE", "FIRE", "WATER", "SEWER"]

# --------------------------------------------------------------------------
# A coherent statutory timeline used by the composite fixtures. Chosen so
# that, under the default 30-day notice window, 30-day protest window and
# 10-day cooling-off period, each step is admissible when the clock is moved
# to the matching instant.
# --------------------------------------------------------------------------
HEARING_START_AT = "2026-09-15T10:00:00Z"
HEARING_END_AT = "2026-09-15T12:00:00Z"
CLOCK_AT_HEARING = "2026-09-15T10:00:00Z"
CLOCK_DURING_PROTEST_WINDOW = "2026-09-20T00:00:00Z"
CLOCK_AFTER_PROTEST_WINDOW = "2026-10-16T00:00:00Z"
EFFECTIVE_DATE_AFTER_PROTEST = "2026-10-16"

# Commitment windows: 30 days long, inside both the police/fire 60-day cap and
# the water/sewer 730-day cap.
COMMITMENT_WINDOW_START = "2026-09-01"
COMMITMENT_WINDOW_END = "2026-09-30"

# A second, later timeline for a successor case whose notice can only be
# published once the predecessor is already effective.
DE_ANNEXATION_HEARING_START_AT = "2026-11-20T10:00:00Z"
DE_ANNEXATION_HEARING_END_AT = "2026-11-20T12:00:00Z"
DE_ANNEXATION_CLOCK_AFTER_PROTEST = "2026-12-21T00:00:00Z"
DE_ANNEXATION_EFFECTIVE_DATE = "2026-12-21"
DE_ANNEXATION_COMMITMENT_WINDOW_START = "2026-11-01"
DE_ANNEXATION_COMMITMENT_WINDOW_END = "2026-11-30"
