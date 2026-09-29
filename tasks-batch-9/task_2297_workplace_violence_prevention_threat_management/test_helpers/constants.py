"""Named business thresholds, weights and fixed instants.

Every value here is stated in the requirements; the tests reference the names so
that an assertion reads as the rule it is checking.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

#: The logical clock before any client sets it.
CLOCK_INITIAL = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Hazard score (six risk terms, floor then cap)
# --------------------------------------------------------------------------

INCIDENT_TERM_CAP_COUNT = 8
INCIDENT_TERM_POINTS_EACH = 5
PROXIMITY_POINTS_LOW = 0
PROXIMITY_POINTS_MODERATE = 8
PROXIMITY_POINTS_HIGH = 20
CASH_TERM_BRACKET_CENTS = 5_000_000
CASH_TERM_POINTS_PER_BRACKET = 4
CASH_TERM_CAP_POINTS = 20
STAFFING_POINTS_ONE_OR_FEWER = 12
STAFFING_POINTS_EXACTLY_TWO = 6
STAFFING_POINTS_THREE_OR_MORE = 0
PUBLIC_ACCESS_POINTS = 10
NIGHT_SHIFT_POINTS = 8
LONE_WORKER_FLOOR_POINTS = 45
HAZARD_SCORE_CAP = 100

MITIGATION_CREDIT_CAP_COUNT = 4
MITIGATION_CREDIT_POINTS_EACH = 5
BARRIER_CREDIT_POINTS = 10

CONTROL_TIER_1_MIN = 60
CONTROL_TIER_2_MIN = 35

# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------

DEFAULT_REFRESH_INTERVAL_DAYS = 365
DEFAULT_PASSING_SCORE = 80
TRAINING_COMPLIANCE_MIN_PCT = 80.00
VACUOUS_COMPLIANCE_PCT = 100.00

# --------------------------------------------------------------------------
# Incident severity
# --------------------------------------------------------------------------

WEAPON_SEVERITY_POINTS = 30
INJURY_POINTS_NONE = 0
INJURY_POINTS_FIRST_AID = 8
INJURY_POINTS_MEDICAL_TREATMENT = 18
INJURY_POINTS_LOST_TIME = 28
INJURY_POINTS_FATALITY = 40
TYPOLOGY_POINTS_TYPE_1_CRIMINAL = 10
TYPOLOGY_POINTS_TYPE_2_CLIENT = 6
TYPOLOGY_POINTS_TYPE_3_COWORKER = 12
TYPOLOGY_POINTS_TYPE_4_DOMESTIC = 8
SEVERITY_SERIOUS_MIN = 20
SEVERITY_CRITICAL_MIN = 40

# --------------------------------------------------------------------------
# Behavioural risk scoring
# --------------------------------------------------------------------------

INTERIM_SEVERITY_MULTIPLIER = 0.60
INTERIM_PRIOR_CASE_POINTS = 8
INTERIM_PRIOR_CASE_CAP = 4
INTERIM_WEAPON_POINTS = 12
INTERIM_SCORE_CAP = 100

DISCIPLINE_WEIGHT_SECURITY = 1.325
DISCIPLINE_WEIGHT_CLINICAL = 1.150
DISCIPLINE_WEIGHT_HR = 1.000
DISCIPLINE_WEIGHT_LEGAL = 0.875
DISCIPLINE_WEIGHT_OPERATIONS = 0.775

BALLOT_POINTS_NO_CONCERN = 5
BALLOT_POINTS_MONITOR = 35
BALLOT_POINTS_ELEVATED = 65
BALLOT_POINTS_IMMINENT = 95

INTERIM_BLEND_WEIGHT = 0.35
BALLOT_BLEND_WEIGHT = 0.65

RISK_BAND_IMMINENT_MIN = 70
RISK_BAND_HIGH_MIN = 45
RISK_BAND_MODERATE_MIN = 20

MIN_VOTING_SEATS = 3
MAX_ASSESSMENT_ROUNDS = 3
OVERRIDE_JUSTIFICATION_MIN_LENGTH = 40

# --------------------------------------------------------------------------
# Protective measures
# --------------------------------------------------------------------------

PROTECTION_WINDOW_DAYS = 14
PROTECTION_WINDOW_MINUTES = 20_160
PROTECTION_WINDOW_HOURS = 336.00
MINUTES_PER_HOUR = 60
ESCORT_BUFFER_MINUTES = 30
AREA_RESTRICTION_CAP_RATIO = 0.25
AUTO_ACTION_DUE_OFFSET_HOURS = 24

# --------------------------------------------------------------------------
# Violent incident log
# --------------------------------------------------------------------------

REQUIRED_LOG_ELEMENT_COUNT = 8
AUTO_APPENDED_ELEMENT_COUNT = 6
RETENTION_YEARS = 5
WORKSITE_HIGH_RISK_INCIDENT_THRESHOLD = 1

# --------------------------------------------------------------------------
# Drills
# --------------------------------------------------------------------------

DRILL_CREDIT_MIN_PCT = 60.00
REQUIRED_DRILLS_PER_YEAR = 2
TRAILING_WINDOW_DAYS = 365

# --------------------------------------------------------------------------
# Inspection readiness
# --------------------------------------------------------------------------

HAZARD_WEIGHT = 30
TRAINING_WEIGHT = 25
LOG_WEIGHT = 20
DRILL_WEIGHT = 15
ACTION_FULL_POINTS = 10
ACTION_PARTIAL_POINTS = 4
ACTION_ZERO_POINTS = 0

PENALTY_BAND_STRONG_MIN = 90
PENALTY_BAND_ADEQUATE_MIN = 75
PENALTY_RATE_STRONG = 0.02
PENALTY_RATE_ADEQUATE = 0.06
PENALTY_RATE_WEAK = 0.12

READY_THRESHOLD_OPEN = 75.00
READY_THRESHOLD_RESTRICTED = 85.00

# --------------------------------------------------------------------------
# Plan review cycle
# --------------------------------------------------------------------------

DEFAULT_REVIEW_INTERVAL_DAYS = 365
FULL_HAZARD_COVERAGE_PCT = 100.00

# --------------------------------------------------------------------------
# Numeric tolerance for two-decimal comparisons
# --------------------------------------------------------------------------

MONEY_TOLERANCE = 0.01
