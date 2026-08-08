"""Domain thresholds and clinic rates named by the PRD."""

# Clock (PRD §2.5) -------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
BASE_CLOCK_UTC = "2026-06-01T00:00:00Z"

# Near-point evaluation (PRD §3.2) --------------------------------------
NPC_BREAK_DIAGNOSTIC_CM = 6.0
NPC_RECOVERY_DIAGNOSTIC_CM = 9.0
NPC_BREAK_DISCHARGE_CM = 5.0
NPC_RECOVERY_DISCHARGE_CM = 7.0

# Accommodative amplitude reference bands (PRD §3.1) --------------------
AMPLITUDE_STANDARD_BASE_D = 15.0
AMPLITUDE_STANDARD_PER_YEAR_D = 0.25
AMPLITUDE_STANDARD_BAND_WIDTH_D = 2.00
AMPLITUDE_FUNCTIONAL_BASE_D = 16.0
AMPLITUDE_FUNCTIONAL_PER_YEAR_D = 0.28
AMPLITUDE_FUNCTIONAL_BAND_WIDTH_D = 1.00

# Composite progress score (PRD §3.7) -----------------------------------
VERGENCE_GOAL_PD = 20.0
ACUITY_GOAL_LOGMAR = 0.10
DISCHARGE_SCORE_THRESHOLD = 80.0
DISCHARGE_SYMPTOM_THRESHOLD = 50.0
REGRESSION_SCORE_THRESHOLD = 40.0
LOW_DELTA_POINTS = 5.0
PLATEAU_CONSECUTIVE_COUNT = 2

DIAGNOSIS_WEIGHTS = {
    # (near_point, amplitude, vergence, symptom)
    "CONVERGENCE_INSUFFICIENCY": (0.40, 0.15, 0.25, 0.20),
    "ACCOMMODATIVE_DYSFUNCTION": (0.20, 0.45, 0.15, 0.20),
    "OCULOMOTOR_DYSFUNCTION": (0.25, 0.25, 0.30, 0.20),
    # AMBLYOPIA uses (acuity, near_point, symptom) only
    "AMBLYOPIA": (0.55, 0.25, 0.20),
}

# Home practice and compliance (PRD §3.6) -------------------------------
HOME_WEIGHTING = 0.5
COMPLIANCE_WINDOW_DAYS = 28
COMPLIANCE_THRESHOLD_PCT = 75.00
REASSESSMENT_LOOKBACK_DAYS = 21
PHASE_INDEX_REQUIRING_REASSESSMENT = 3

# Scheduling (PRD §3.5) --------------------------------------------------
ROOM_TURNOVER_BUFFER_MINUTES = 15
THERAPIST_TURNOVER_BUFFER_MINUTES = 0
THERAPIST_DAILY_CAP_MINUTES = 180

# Billable-unit ladder for TIMED_THERAPEUTIC_ACTIVITY (PRD §3.5) --------
# (max_minutes_inclusive, units); anything beyond 82 minutes bills the cap of 6.
TIMED_UNIT_STEPS = [(7, 0), (22, 1), (37, 2), (52, 3), (67, 4), (82, 5)]
TIMED_UNIT_CAP = 6

# Clinic rates (PRD §3.5 / §3.10) ---------------------------------------
RATE_TIMED_THERAPEUTIC_ACTIVITY = 42.00
RATE_FLAT_ORTHOPTIC_TRAINING = 155.00
RATE_EVALUATION_ENCOUNTER = 210.00
CLINIC_RATES = {
    "TIMED_THERAPEUTIC_ACTIVITY": RATE_TIMED_THERAPEUTIC_ACTIVITY,
    "FLAT_ORTHOPTIC_TRAINING": RATE_FLAT_ORTHOPTIC_TRAINING,
    "EVALUATION_ENCOUNTER": RATE_EVALUATION_ENCOUNTER,
}

# Reauthorization (PRD §2.7 rung 32) ------------------------------------
REAUTH_LOOKBACK_DAYS = 30

# Occlusion (PRD §3.8) ---------------------------------------------------
OCCLUSION_MAX_DAILY_HOURS = 7
TAPER_STEP_HOURS = 2
TAPER_ADHERENCE_THRESHOLD_PCT = 70.0
TAPER_ACUITY_GAIN_LOGMAR = 0.20
OCCLUSION_DOSE_LADDER = {
    ("YOUNG", "MILD"): 2,
    ("YOUNG", "MODERATE"): 3,
    ("YOUNG", "SEVERE"): 4,
    ("SCHOOL", "MILD"): 2,
    ("SCHOOL", "MODERATE"): 4,
    ("SCHOOL", "SEVERE"): 6,
    ("OLDER", "MILD"): 3,
    ("OLDER", "MODERATE"): 5,
    ("OLDER", "SEVERE"): 8,
}

# Kit and equipment (PRD §3.9) ------------------------------------------
SALVAGE_FLOOR_RATIO = 0.20
CONDITION_MULTIPLIERS = {"GOOD": 0.00, "FAIR": 0.25, "DAMAGED": 0.60, "LOST": 1.00}
RECALL_DUE_DAYS = 7

# Referral SLA (PRD §3.11) ----------------------------------------------
URGENT_REFERRAL_SLA_HOURS = 24
ROUTINE_REFERRAL_SLA_HOURS = 120
MAX_REFERRAL_ATTEMPTS = 3

# Claim caps (PRD §3.10) -------------------------------------------------
MAX_APPEAL_ATTEMPTS = 2
MAX_ASSESSMENT_AMENDMENTS = 2

# Discharge (PRD §3.11) --------------------------------------------------
LOST_TO_FOLLOW_UP_LOOKBACK_DAYS = 60

# Pagination (PRD §2.3) --------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
