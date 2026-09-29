"""Named constants taken verbatim from the PRD.

Nothing here is derived or guessed: every value below appears literally in the
PRD prose, so a test can reference the constant instead of repeating a magic
number. Section references point at the paragraph the value is stated in.
"""

# ----------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ----------------------------------------------------------------------
# "Before the first such call the clock reads exactly 2026-08-01T00:00:00Z".
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ----------------------------------------------------------------------
# Pagination (PRD 2.3)
# ----------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ----------------------------------------------------------------------
# Recruitment posture and the fill calculation (PRD 3.1)
# ----------------------------------------------------------------------
FILLED_THRESHOLD = 1.0000
ON_TARGET_THRESHOLD = 0.8000
INCENTIVE_BOOST_PCT = 0.25
BOOSTED_MULTIPLIER = 1.25
UNBOOSTED_MULTIPLIER = 1.00

# ----------------------------------------------------------------------
# Enumeration (PRD 3.2)
# ----------------------------------------------------------------------
# "the test passes when that age is at most 14 days - an age of exactly 14 days
# is still on time."
ENUMERATION_DUE_DAYS = 14
SECONDS_PER_DAY = 86400
MIN_TV_SETS_FOR_PASS = 1

# ----------------------------------------------------------------------
# Rolling compliance (PRD 3.6)
# ----------------------------------------------------------------------
ROLLING_WINDOW_DAYS = 30
MIN_COMPLIANT_DAY_MINUTES = 30
MINUTES_PER_DAY = 1440

# ----------------------------------------------------------------------
# The editing pass credit factors (PRD 3.6 step 3)
# ----------------------------------------------------------------------
CREDIT_FACTOR_INHOME_TUNER = 1.0
CREDIT_FACTOR_STREAMING_SDK = 1.0
CREDIT_FACTOR_PORTABLE_OOH = 0.5
METHODOLOGY_CREDIT_FACTOR = {
    "INHOME_TUNER": CREDIT_FACTOR_INHOME_TUNER,
    "STREAMING_SDK": CREDIT_FACTOR_STREAMING_SDK,
    "PORTABLE_OOH": CREDIT_FACTOR_PORTABLE_OOH,
}

# ----------------------------------------------------------------------
# Cooperation incentives (PRD 3.4)
# ----------------------------------------------------------------------
SECONDS_PER_TENURE_MONTH = 2592000  # "divided by 2592000 seconds and floored"
TENURE_MULTIPLIER_UNDER_6M = 1.000
TENURE_MULTIPLIER_6M_TO_23M = 1.075
TENURE_MULTIPLIER_24M_PLUS = 1.150
TENURE_BAND_6M = 6
TENURE_BAND_24M = 24
COMPLIANCE_BONUS_PCT = 0.0855
COMPLIANCE_BONUS_THRESHOLD = 0.90
OOH_SUPPLEMENT_PCT = 0.0405
FAULT_PENALTY_PCT = 0.25
INCENTIVE_PERIOD_CAP_CENTS = 5000

# ----------------------------------------------------------------------
# Editing rule set bounds (PRD 3.5)
# ----------------------------------------------------------------------
MIN_ASCRIPTION_MINUTES = 0
MAX_ASCRIPTION_MINUTES = 240
MIN_INVALID_TUNING_MAX_MINUTES = 1
MIN_OUTLIER_HOUSEHOLD_MINUTES_CAP = 1
MIN_OUTLIER_WEIGHT_RATIO_CAP = 1.0000
MIN_FAULT_MISSING_MINUTES_THRESHOLD = 1

# ----------------------------------------------------------------------
# Universe vintages (PRD 3.5)
# ----------------------------------------------------------------------
UNIVERSE_VINTAGE_MIN_DAYS_BETWEEN_PUBLICATIONS = 28

# ----------------------------------------------------------------------
# Client tiers (PRD 3.8)
# ----------------------------------------------------------------------
TIER_TABLE = {
    "BASIC": {
        "tier_base_fee_cents": 25000,
        "delivery_sla_hours": 168,
        "custom_analysis_quota": 0,
    },
    "STANDARD": {
        "tier_base_fee_cents": 65000,
        "delivery_sla_hours": 72,
        "custom_analysis_quota": 3,
    },
    "PREMIUM": {
        "tier_base_fee_cents": 120000,
        "delivery_sla_hours": 24,
        "custom_analysis_quota": 10,
    },
}
BASIC_BASE_FEE_CENTS = 25000
STANDARD_BASE_FEE_CENTS = 65000
PREMIUM_BASE_FEE_CENTS = 120000
BASIC_SLA_HOURS = 168
STANDARD_SLA_HOURS = 72
PREMIUM_SLA_HOURS = 24

MIN_REQUESTED_CELL_COUNT = 0
MAX_REQUESTED_CELL_COUNT = 24
REVISION_LIMIT = 2
HOLD_CREDIT_PCT = 0.05

# ----------------------------------------------------------------------
# Deliverable billing (PRD 3.8)
# ----------------------------------------------------------------------
CELL_SURCHARGE_CENTS = 5000
VOLUME_BRACKET_LOW_CEILING = 80000
VOLUME_BRACKET_MID_CEILING = 150000
VOLUME_DISCOUNT_RATE_UNDER_80000 = 0.00
VOLUME_DISCOUNT_RATE_80000_TO_149999 = 0.10
VOLUME_DISCOUNT_RATE_150000_PLUS = 0.15
PENALTY_RATE_UNDER_80000 = 0.000
PENALTY_RATE_80000_TO_149999 = 0.015
PENALTY_RATE_150000_PLUS = 0.025

# ----------------------------------------------------------------------
# Methodology impact (PRD 3.9)
# ----------------------------------------------------------------------
IMPACT_WEIGHT_CAP = 0.40
IMPACT_WEIGHT_TUNING = 0.35
IMPACT_WEIGHT_ASCRIPTION = 0.25
IMPACT_CAP_DIVISOR = 2.5
IMPACT_TUNING_DIVISOR = 300
IMPACT_ASCRIPTION_DIVISOR = 60
IMPACT_SUBSCORE_CAP = 1.0
TIER_MATERIAL_THRESHOLD = 0.1500
TIER_MODERATE_THRESHOLD = 0.0500
NOTIFICATION_LEAD_HOURS = {"MINOR": 72, "MODERATE": 336, "MATERIAL": 720}
LEAD_HOURS_MINOR = 72
LEAD_HOURS_MODERATE = 336
LEAD_HOURS_MATERIAL = 720

# ----------------------------------------------------------------------
# Field length and shape bounds (PRD 2.6 step 7, 3.1, 3.5, 3.8, 3.9)
# ----------------------------------------------------------------------
MARKET_CODE_PATTERN = "DMA-###"
SERIAL_NO_PATTERN = "MT-######"
MAX_MARKET_NAME_LENGTH = 120
MAX_CLIENT_NAME_LENGTH = 120
MAX_RULE_SET_LABEL_LENGTH = 60
MAX_TITLE_LENGTH = 160
MAX_QUESTION_LENGTH = 400
MAX_AUDITOR_NOTE_LENGTH = 400
MAX_STATION_CODE_LENGTH = 24
MIN_ROSTER_PERSONS_COUNT = 1
MAX_ROSTER_PERSONS_COUNT = 12
MIN_TV_SETS_COUNT = 0
MAX_TV_SETS_COUNT = 8
MAX_CONTRACT_MARKET_IDS = 10
MAX_AFFECTED_MARKET_IDS = 10
