"""Business constants the PRD fixes numerically.

Nothing here is a test expectation on its own — these are the contract's own
literals, restated once so a test can name them instead of repeating them.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Fire potential index (PRD §3.2)
# --------------------------------------------------------------------------
FPI_WINDOW_HOURS_BEFORE = 24
FPI_WINDOW_HOURS_AFTER = 24
WIND_BASE_MPH = 20
WIND_MULTIPLIER = 2.5
DRYNESS_FUEL_REFERENCE_PCT = 12
DRYNESS_FUEL_MULTIPLIER = 4
TERRAIN_COMPONENT = {"TIER_3": 100, "TIER_2": 70, "TIER_1": 40, "NON_HFTD": 10}
INSPECTION_OVERDUE_PENALTY = 30
DAYS_PER_CYCLE_MONTH = 30
FPI_WEIGHT_WIND = 0.35
FPI_WEIGHT_DRYNESS = 0.30
FPI_WEIGHT_TERRAIN = 0.20
FPI_WEIGHT_EQUIPMENT = 0.15
HARDENING_DISCOUNT_FACTOR = 0.40
FPI_TIER_CUT_POINTS = {"R2": 20, "R3": 40, "R4": 60, "R5": 75}

# --------------------------------------------------------------------------
# Hardening ledger and the mitigation portfolio (PRD §3.3)
# --------------------------------------------------------------------------
COVERED_CONDUCTOR_CREDIT = 0.6
UNDERGROUNDING_CREDIT = 1.0
HARDENED_FRACTION_CAP = 1.0000
PROGRAM_EFFECTIVENESS = {
    "COVERED_CONDUCTOR": 0.62,
    "UNDERGROUNDING": 1.00,
    "FAST_TRIP_SETTING": 0.45,
    "INSPECTION_CYCLE": 0.18,
}
TERRAIN_MULTIPLIER = {"TIER_3": 1.5, "TIER_2": 1.2, "TIER_1": 1.0, "NON_HFTD": 0.5}
MAX_REVIEW_ROUNDS = 2

# --------------------------------------------------------------------------
# Scope determination (PRD §3.4)
# --------------------------------------------------------------------------
FAST_TRIP_EXEMPTION_JUSTIFICATION = "FAST_TRIP_MITIGATED_R4"
EVENT_CANCELLED_JUSTIFICATION = "EVENT_CANCELLED"

# --------------------------------------------------------------------------
# Notification sequencing (PRD §3.5)
# --------------------------------------------------------------------------
STAGE_MINIMUM_LEAD_MINUTES = {
    "ADVANCE_48H": 2880,
    "ADVANCE_24H": 1440,
    "IMMINENT_1H": 60,
    "ACTIVATION": 0,
    "RESTORATION": 0,
}
CHANNEL_PRIORITY = ["SMS", "VOICE", "EMAIL"]
TIME_CRITICAL_STAGES = ["IMMINENT_1H", "ACTIVATION"]
TIME_CRITICAL_LANGUAGES = ["EN", "ES"]
ALL_LANGUAGES = ["EN", "ES", "ZH", "TL", "VI"]
PRE_ONSET_STAGES = ["ADVANCE_48H", "ADVANCE_24H", "IMMINENT_1H"]

# --------------------------------------------------------------------------
# Arming and resource centers (PRD §3.6)
# --------------------------------------------------------------------------
NET_BENEFIT_ARM_THRESHOLD = 0.25
RESOURCE_CENTER_RESET_BUFFER_MINUTES = 240

# --------------------------------------------------------------------------
# Net-benefit accounting (PRD §3.8)
# --------------------------------------------------------------------------
MEDICAL_BASELINE_WEIGHT = 4
CRITICAL_FACILITY_WEIGHT = 10
IMPACT_DIVISOR = 10
CREDIT_RATE_BANDS = [(0, 0.00), (20, 0.05), (60, 0.12), (200, 0.20)]
NET_BENEFIT_DENOMINATOR_FLOOR = 0.01

# --------------------------------------------------------------------------
# Plan filings (PRD §3.9)
# --------------------------------------------------------------------------
UNDERGROUND_TARGET_MILES = 20.0
UNDERGROUND_WEIGHT_POINTS = 40
COVERED_CONDUCTOR_TARGET_MILES = 50.0
COVERED_CONDUCTOR_WEIGHT_POINTS = 30
LEAD_TIME_TARGET_MINUTES = 2880
LEAD_TIME_WEIGHT_POINTS = 30
MAX_DEFICIENCY_ROUNDS = 3

# --------------------------------------------------------------------------
# Decimal tolerances — the PRD pins exact scales, so comparisons are exact to
# within a half unit of the last published place.
# --------------------------------------------------------------------------
TOLERANCE_4DP = 0.00005
TOLERANCE_2DP = 0.005
TOLERANCE_1DP = 0.05

# Identifiers that resolve to nothing.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_2 = "11111111-1111-4111-8111-111111111111"
