"""Domain thresholds and defaults drawn from the PRD's stated numbers."""

# The logical clock's startup instant (PRD §2.5).
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_DATE = "2026-08-01"

# Carrier policy-knob defaults (PRD §3.1).
CARRIER_DEFAULTS = {
    "safety_rating": "SATISFACTORY",
    "mvr_validity_days": 365,
    "annual_review_interval_days": 365,
    "annual_review_grace_days": 30,
    "mvr_point_threshold": 7,
    "rehire_cooldown_days": 180,
    "medical_cert_grace_days": 15,
}

# Adjudication scoring (PRD §3.4).
SCORING = {
    "POINT_WEIGHT": 1.0,
    "SERIOUS_VIOLATION_WEIGHT": 4.0,
    "PREVENTABLE_CRASH_WEIGHT": 6.0,
    "EXPERIENCE_CREDIT_PER_YEAR": 1.5,
    "MAX_EXPERIENCE_CREDIT": 6.0,
    "SATISFACTORY_MULTIPLIER": 1.00,
    "CONDITIONAL_MULTIPLIER": 1.25,
    "UNSATISFACTORY_MULTIPLIER": 1.50,
}

# Road test scoring (PRD §3.6).
ROAD_TEST = {
    "WEIGHT_PRETRIP": 0.25,
    "WEIGHT_SKILLS": 0.35,
    "WEIGHT_ROAD": 0.40,
    "PASS_THRESHOLD": 80.0,
    "ROAD_FLOOR": 70,
    "MAX_ATTEMPTS": 3,
    "SLOT_MINUTES": 180,
}

# Qualification-file weights (PRD §3.7).
DOC_WEIGHTS = {
    "APPLICATION_FORM": 3,
    "CDL_COPY": 2,
    "MVR_INITIAL": 3,
    "PSP_REPORT": 2,
    "CRIMINAL_CHECK": 1,
    "EMPLOYMENT_VERIFICATION": 4,
    "CLEARINGHOUSE_QUERY": 3,
    "DRUG_TEST_RESULT": 3,
    "ROAD_TEST_CERT": 3,
    "MEDICAL_CERT": 4,
    "MVR_ANNUAL": 3,
    "ANNUAL_REVIEW_CERT": 2,
}
TOTAL_DOC_WEIGHT = 33
PRE_HIRE_DENOMINATOR = 28
ANNUAL_REVIEW_DENOMINATOR = 30

# Employment-history coverage (PRD §3.3).
LOOKBACK_DAYS = 1095
MAX_UNEXPLAINED_GAP_DAYS = 30
NO_RESPONSE_WAIT_DAYS = 14
GOOD_FAITH_ROUNDS = 3

# Windows and bands.
DISPUTE_WINDOW_DAYS = 5
CONSENT_VALIDITY_DAYS = 365
WATCH_WINDOW_DAYS = 60
IMMINENT_WINDOW_DAYS = 15
MAX_DILUTE_RECOLLECTIONS = 1
ORIENTATION_BUFFER_HOURS = 12
DEFICIENCY_RESTRICT_RATIO = 0.2500

# Tuition tiers (PRD §3.9).
TUITION = {
    "TIER_HIGH_MIN_CENTS": 20000,
    "TIER_MID_MIN_CENTS": 10000,
    "BONUS_PCT_HIGH": 0.00,
    "BONUS_PCT_MID": 0.05,
    "BONUS_PCT_LOW": 0.10,
}

# Pagination (PRD §2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# Convenient reusable literals for tests.
DEFAULT_RECRUITER_USER_ID = "rec-001"
DEFAULT_AUDITOR_USER_ID = "aud-900"
DEFAULT_EXAMINER_USER_ID = "exam-501"
