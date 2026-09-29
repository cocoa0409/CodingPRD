"""Named constants for every threshold, divisor, weight and duration the PRD fixes.

Tests import these instead of repeating bare numbers, so the number appears once
next to the rule it belongs to.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

CLOCK_START = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Census posture bands (PRD §2.8)
# ---------------------------------------------------------------------------

CONSTRAINED_POSTURE_FRACTION = 0.20

# ---------------------------------------------------------------------------
# Designation compliance scoring (PRD §3.2)
# ---------------------------------------------------------------------------

STAFFING_SUBSCORE_WEIGHT = 0.45
EQUIPMENT_SUBSCORE_WEIGHT = 0.35
VOLUME_SUBSCORE_WEIGHT = 0.20
CREDENTIAL_MIN_FTE = 0.5
TRANSPORT_CAP_SCORE = 69.99
MAX_SUBMISSION_ROUNDS = 3

# ---------------------------------------------------------------------------
# Referral triage priority (PRD §3.3)
# ---------------------------------------------------------------------------

TRIAGE_LEVEL_WEIGHT = 0.40
TRIAGE_PREMATURITY_WEIGHT = 0.25
TRIAGE_WEIGHT_WEIGHT = 0.20
TRIAGE_KIND_WEIGHT = 0.15

TRIAGE_LEVEL_POINTS = {
    "LEVEL_I": 25,
    "LEVEL_II": 50,
    "LEVEL_III": 75,
    "LEVEL_IV": 100,
}

TRIAGE_KIND_POINTS = {
    "MATERNAL_ANTENATAL": 100,
    "INBOUND_NEONATAL": 50,
    "BACK_TRANSFER": 0,
}

MAX_INFO_REQUEST_ROUNDS = 2

# ---------------------------------------------------------------------------
# Bed holds (PRD §3.4)
# ---------------------------------------------------------------------------

MATERNAL_HOLD_MINUTES = 720
NEONATAL_HOLD_MINUTES = 240
FORECAST_EXPIRING_HOLD_WINDOW_MINUTES = 60

# ---------------------------------------------------------------------------
# Surge escalation (PRD §3.5)
# ---------------------------------------------------------------------------

SURGE_TIER_1_RATIO = 0.80
SURGE_TIER_2_RATIO = 0.90
SURGE_TIER_3_RATIO = 1.00

SURGE_WAIVER_RATIOS = {
    "TIER_1": 1.10,
    "TIER_2": 1.25,
    "TIER_3": 1.50,
}

SURGE_BED_CAPS = {
    "TIER_1": 2,
    "TIER_2": 4,
    "TIER_3": 6,
}

# ---------------------------------------------------------------------------
# Transport (PRD §3.6)
# ---------------------------------------------------------------------------

GROUND_DECONTAMINATION_MINUTES = 45
AIR_DECONTAMINATION_MINUTES = 90

STABILIZATION_BASE_SCORE = 100
STABILIZATION_MISS_PENALTY = 8
STABILIZATION_COMPLETE_THRESHOLD = 85

STABILIZATION_TEMP_MIN_C = 36.5
STABILIZATION_TEMP_MAX_C = 37.5
STABILIZATION_GLUCOSE_MIN_MG_DL = 45
STABILIZATION_SPO2_MIN_PCT = 90
STABILIZATION_SPO2_MAX_PCT = 95
# The mean-pressure target has no fixed floor: it is the numeric value of the
# referral's gestational_age_weeks.

# ---------------------------------------------------------------------------
# Developmental care bundle (PRD §3.7)
# ---------------------------------------------------------------------------

BUNDLE_KANGAROO_WEIGHT = 0.35
BUNDLE_FAMILY_PRESENCE_WEIGHT = 0.25
BUNDLE_CLUSTER_CARE_WEIGHT = 0.20
BUNDLE_LIGHT_CYCLING_WEIGHT = 0.20

BUNDLE_KANGAROO_TARGET_SESSIONS = 3
BUNDLE_FAMILY_PRESENCE_TARGET_MINUTES = 720
BUNDLE_KANGAROO_SESSION_MIN_MINUTES = 60
BUNDLE_BACK_TRANSFER_READY_THRESHOLD = 60.0

# ---------------------------------------------------------------------------
# Milk handling (PRD §3.7)
# ---------------------------------------------------------------------------

MOTHERS_OWN_SHELF_LIFE_HOURS = 96
DONOR_PASTEURIZED_SHELF_LIFE_HOURS = 24

# ---------------------------------------------------------------------------
# Surveillance (PRD §3.9)
# ---------------------------------------------------------------------------

CLABSI_RATE_MULTIPLIER = 1000
NETWORK_CLABSI_BENCHMARK = 1.50

BIRTH_WEIGHT_RISK_WEIGHTS = {
    "UNDER_1000": 1.30,
    "1000_TO_1499": 1.15,
    "1500_TO_2499": 1.00,
    "2500_AND_ABOVE": 0.85,
}
EMPTY_COHORT_RISK_WEIGHT = 1.0000

# ---------------------------------------------------------------------------
# Follow-up clinic (PRD §3.9)
# ---------------------------------------------------------------------------

FOLLOWUP_WINDOW_START_DAYS = 14
FOLLOWUP_WINDOW_END_DAYS = 90
FOLLOWUP_HIGH_RISK_BIRTH_WEIGHT_GRAMS = 1000
FOLLOWUP_ELIGIBLE_BIRTH_WEIGHT_GRAMS = 1500
FOLLOWUP_ELIGIBLE_GESTATIONAL_AGE_WEEKS = 32.0
FOLLOWUP_ELIGIBLE_VENTILATOR_DAYS = 7
