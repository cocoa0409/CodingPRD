"""Domain constants for the Lead Service Line Inventory & Replacement API.

Every value here is transcribed from the PRD so that test bodies never restate a
magic number twice.
"""

API_PREFIX = "/lsl"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

#: The service starts with its logical clock at exactly this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Evidence tier ranks and confidence weights
# ---------------------------------------------------------------------------

TIER_RANK_BY_SOURCE_TYPE = {
    "HISTORIC_RECORD": 1,
    "PREDICTIVE_MODEL": 2,
    "WATER_SAMPLING": 3,
    "VISUAL_INSPECTION": 4,
    "POTHOLE": 5,
}

CONFIDENCE_WEIGHT_BY_SOURCE_TYPE = {
    "HISTORIC_RECORD": 0.40,
    "PREDICTIVE_MODEL": 0.55,
    "WATER_SAMPLING": 0.70,
    "VISUAL_INSPECTION": 0.85,
    "POTHOLE": 1.00,
}

#: Source types admissible while a line is still on the records basis.
RECORDS_BASIS_SOURCE_TYPES = ("HISTORIC_RECORD", "PREDICTIVE_MODEL")

#: Source types that put a line onto the field basis when present on both sides.
FIELD_SOURCE_TYPES = ("VISUAL_INSPECTION", "POTHOLE")

#: Worst-of classification precedence, strongest first.
CLASSIFICATION_PRECEDENCE = ("LEAD", "GRR", "UNKNOWN", "NON_LEAD")

# ---------------------------------------------------------------------------
# Certainty score weights
# ---------------------------------------------------------------------------

CERTAINTY_WEAKER_SIDE_WEIGHT = 0.6
CERTAINTY_STRONGER_SIDE_WEIGHT = 0.4

# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

MIN_REQUIRED_SAMPLE_COUNT = 5
SAMPLE_QUOTA_FRACTION = 0.05
ACTION_LEVEL_PPB = 15.0
PERCENTILE_RANK_FRACTION = 0.90
CONFIDENCE_FLOOR = 0.8000

# ---------------------------------------------------------------------------
# Crew scheduling
# ---------------------------------------------------------------------------

TRAVEL_BUFFER_MINUTES = 45
MAX_APPOINTMENT_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Notifications / publication
# ---------------------------------------------------------------------------

NOTIFICATION_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Replacement priority score
# ---------------------------------------------------------------------------

PRIORITY_MATERIAL_LEAD = 50.0
PRIORITY_MATERIAL_GRR = 35.0
PRIORITY_MATERIAL_NON_LEAD = 0.0
PRIORITY_UNKNOWN_BASE = 40.0
PRIORITY_VERIFIED_BONUS = 15.0
PRIORITY_DISADVANTAGED_BONUS = 25.0
PRIORITY_SENSITIVE_POPULATION_BONUS = 10.0
PRIORITY_COORDINATION_TIERS = ((90, 20.0), (180, 12.0), (365, 5.0))
PRIORITY_COORDINATION_NONE = 0.0
PRIORITY_CAP = 100.0
PRIORITY_FLOOR = 0.0
PRIORITY_CONSENT_BARRIER_PENALTY = 8.0
PRIORITY_EQUITY_FLOOR = 65.0
PRIORITY_EQUITY_FLOOR_CLASSIFICATIONS = ("LEAD", "GRR")

# ---------------------------------------------------------------------------
# Program posture
# ---------------------------------------------------------------------------

UNKNOWN_SHARE_RESTRICT_THRESHOLD_PCT = 10.00

# ---------------------------------------------------------------------------
# Flushing guidance
# ---------------------------------------------------------------------------

PI = 3.141592653589793
FLUSHING_BASE_MINUTES = 30
FLUSHING_LITRES_PER_MINUTE_DIVISOR = 20.0
FLUSHING_VOLUME_FACTOR = 3
FLUSHING_PARTIAL_PENALTY_MINUTES = 15
FLUSHING_REOPTIMIZATION_MULTIPLIER = 1.5
FLUSHING_NORMAL_MULTIPLIER = 1

# ---------------------------------------------------------------------------
# Compliance credit
# ---------------------------------------------------------------------------

PARTIAL_CREDIT_FACTOR = 0.5
EQUITY_TIERS = (
    (60.0, "TIER_A", 1.20),
    (40.0, "TIER_B", 1.10),
    (20.0, "TIER_C", 1.00),
)
EQUITY_TIER_FALLBACK = ("TIER_D", 0.90)
MANDATE_FRACTION = 0.10
DEFERRAL_TIERS = ((20.0, 3), (10.0, 2))
DEFERRAL_FALLBACK = 1

# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

MONEY_DECIMALS = 0
STANDARD_DECIMALS = 2
CONFIDENCE_DECIMALS = 4

# ---------------------------------------------------------------------------
# Validation ladder rung numbers (the normative precedence order)
# ---------------------------------------------------------------------------

RUNG_AUTHENTICATION = 10
RUNG_AUTHORIZATION = 20
RUNG_SCHEMA = 30
RUNG_ENUM = 32
RUNG_INTERVAL_COHERENCE = 34
RUNG_PAGINATION = 36
RUNG_PATH_RESOLUTION = 40
RUNG_BODY_FK_RESOLUTION = 42
RUNG_CREW_IDENTITY = 45
RUNG_SEGREGATION_OF_DUTIES = 48
RUNG_STALE_VERSION = 50
RUNG_CONSENT_RESOLUTION = 52
RUNG_DECLARED_TRANSITION = 55
RUNG_LINE_ELIGIBILITY = 56
RUNG_EVIDENCE_RETRACTION_IDEMPOTENCE = 57
RUNG_FROZEN_POSTURE = 58
RUNG_RESTRICTED_POSTURE = 59
RUNG_REFERENTIAL_BUSINESS_GATE = 60
RUNG_SAFETY_GATE = 65
RUNG_UNIQUENESS_MEMBERSHIP_SHAPE = 70
RUNG_TEMPORAL_CONFLICT = 75
RUNG_CAPACITY_CONFLICT = 78
RUNG_EQUITY_BREACH = 85
RUNG_FUNDING_SUFFICIENCY = 90
