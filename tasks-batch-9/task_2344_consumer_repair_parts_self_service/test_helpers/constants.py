"""Domain constants stated in the PRD: thresholds, weights, multipliers and caps."""

API_PREFIX = "/repair-program"

# --------------------------------------------------------------------------- #
# The logical clock (PRD §2.4)
# --------------------------------------------------------------------------- #
CLOCK_START = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------- #
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------- #
# Eligibility, warranty and risk (PRD §3.5)
# --------------------------------------------------------------------------- #
ASSESSMENT_VALIDITY_DAYS = 60
INSTALL_MINUTES_NORMALIZER = 120

TIER_RISK_WEIGHT = {
    "TIER_A_SELF_SERVICE": 0.10,
    "TIER_B_GUIDED": 0.40,
    "TIER_C_AUTHORIZED_ONLY": 0.80,
    "TIER_D_NON_SERVICEABLE": 1.00,
}
SAFETY_RISK_WEIGHT = {
    "UNRESTRICTED": 0.10,
    "SAFETY_RESTRICTED_BATTERY": 0.60,
    "SAFETY_RESTRICTED_HIGH_VOLTAGE": 0.90,
    "PAIRED_SECURITY": 0.70,
}
RISK_TIER_COEFFICIENT = 0.40
RISK_SAFETY_COEFFICIENT = 0.35
RISK_INSTALL_COEFFICIENT = 0.25

LIABILITY_WARNING_PREFIX = "LW-"
LIABILITY_WARNING_REVISION_SEPARATOR = "-R"

# --------------------------------------------------------------------------- #
# Order pricing (PRD §3.6)
# --------------------------------------------------------------------------- #
CONSUMER_BUYER_MULTIPLIER = 1.00
PROVIDER_BUYER_MULTIPLIER = 0.82

VOLUME_TIER_1_MIN_QTY = 10
VOLUME_TIER_1_MULTIPLIER = 0.92
VOLUME_TIER_2_MIN_QTY = 25
VOLUME_TIER_2_MULTIPLIER = 0.85
VOLUME_BASE_MULTIPLIER = 1.00

TIER_SURCHARGE_MULTIPLIER = {
    "TIER_A_SELF_SERVICE": 1.00,
    "TIER_B_GUIDED": 1.05,
    "TIER_C_AUTHORIZED_ONLY": 1.12,
}

DOC_FEE_BASE_CENTS = 500
DOC_FEE_PER_WARNING_CENTS = 120

CONSUMER_CORE_DEPOSIT_CAP_CENTS = 50000

MIN_LINE_QUANTITY = 1
MAX_LINE_QUANTITY = 500

# --------------------------------------------------------------------------- #
# Rental kits (PRD §3.6)
# --------------------------------------------------------------------------- #
RENTAL_TURNAROUND_DAYS = 2

# --------------------------------------------------------------------------- #
# Core return settlement (PRD §3.7)
# --------------------------------------------------------------------------- #
CORE_RETURN_WINDOW_DAYS = 30
CORE_DECAY_PER_DAY = 0.05
CORE_FORFEIT_DAYS = 20
CORE_CONDITION_MULTIPLIER = {
    "INTACT": 1.00,
    "DAMAGED_SHELL": 0.70,
    "INCOMPLETE": 0.40,
    "NON_RETURNABLE": 0.00,
}

# --------------------------------------------------------------------------- #
# Calibration (PRD §3.7)
# --------------------------------------------------------------------------- #
CALIBRATION_TOLERANCE_PPM = 150
CALIBRATION_ATTEMPT_CAP = 3
MEASURED_OFFSET_PPM_MIN = -100000
MEASURED_OFFSET_PPM_MAX = 100000

# --------------------------------------------------------------------------- #
# Provider programme (PRD §3.8)
# --------------------------------------------------------------------------- #
TECHS_PER_CERT = 4
CERT_CREDIT_COST = 2
MIN_TRAINING_CREDIT_GRANT = 2
PASSING_EXAM_SCORE = 70
MIN_TECHNICIAN_COUNT = 1
MAX_TECHNICIAN_COUNT = 500

CERT_COVERAGE_WEIGHT = 0.45
BREACH_WEIGHT = 0.35
CALIBRATION_WEIGHT = 0.20
BREACH_CAP = 5

SCORE_BAND_TIER_1_MIN = 85
SCORE_BAND_TIER_2_MIN = 65

SUSPENSION_REASON_CERT_COVERAGE_LOST = "CERT_COVERAGE_LOST"
BLOCKED_REASON_SAFETY_RESTRICTION = "SAFETY_RESTRICTION_ON_PART"

# --------------------------------------------------------------------------- #
# Defective returns and credit (PRD §3.9)
# --------------------------------------------------------------------------- #
GOODWILL_FACTOR = 0.50
ROOT_CAUSE_FACTOR = {
    "MANUFACTURING_DEFECT": 1.00,
    "PART_AUTHENTICATION_FAILURE": 1.00,
    "UNDETERMINED": 0.50,
    "PROVIDER_INSTALL_ERROR": 0.00,
    "CUSTOMER_MISUSE": 0.00,
}
UNCONFIRMED_DEFECT_FACTOR_CAP = 0.25

# --------------------------------------------------------------------------- #
# Long-tail demand forecast (PRD §3.9)
# --------------------------------------------------------------------------- #
TRAILING_WINDOW_DAYS = 180
TRAILING_WINDOW_MONTHS = 6
MIN_HORIZON_MONTHS = 1
MAX_HORIZON_MONTHS = 60

BAND_MULTIPLIER = {
    "CURRENT": 1.00,
    "LEGACY": 1.35,
    "LONG_TAIL": 1.80,
}
BAND_CURRENT_MAX_MONTHS = 12
BAND_LEGACY_MAX_MONTHS = 60

SAFETY_STOCK_PCT_SMALL = 0.30
SAFETY_STOCK_PCT_MEDIUM = 0.20
SAFETY_STOCK_PCT_LARGE = 0.12
SAFETY_STOCK_SMALL_THRESHOLD = 50
SAFETY_STOCK_MEDIUM_THRESHOLD = 500

MANDATE_BUFFER_RATIO = 0.25

PIPELINE_TRAILING_WEIGHT = 0.60
PIPELINE_OPEN_WEIGHT = 0.40

# --------------------------------------------------------------------------- #
# Compliance obligations (PRD §3.2)
# --------------------------------------------------------------------------- #
AT_RISK_LEAD_DAYS = 90
MIN_MANDATE_YEARS = 0
MAX_MANDATE_YEARS = 15
END_OF_DAY_SUFFIX = "T23:59:59.999Z"

# --------------------------------------------------------------------------- #
# Documentation revisions (PRD §3.4)
# --------------------------------------------------------------------------- #
REVISION_CYCLE_CAP = 3

# --------------------------------------------------------------------------- #
# Structural bounds (PRD §3.1, §3.2, §3.3)
# --------------------------------------------------------------------------- #
MIN_CODE_LENGTH = 3
MAX_CODE_LENGTH = 32
MIN_REGION_CODE_LENGTH = 2
MAX_REGION_CODE_LENGTH = 8
MIN_INSTALL_MINUTES = 1
MAX_INSTALL_MINUTES = 600
