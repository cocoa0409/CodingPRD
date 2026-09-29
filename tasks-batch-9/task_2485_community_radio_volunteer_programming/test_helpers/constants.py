"""Domain thresholds and numeric constants stated in the PRD."""

# --- The station logical clock (PRD §2.4) ---
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Pagination bounds (PRD §2.3) ---
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --- Certification and curriculum (PRD §3.1) ---
CERTIFICATION = {
    "PASS_SCORE": 80,
    "MIN_EXAM_SCORE": 0,
    "MAX_EXAM_SCORE": 100,
    "EXPIRY_MONTHS": 24,
    "COOLING_OFF_DAYS": 14,
    "MAX_ATTEMPTS": 3,
}

CORE_CERT_TYPES = ["BOARD_OPERATION", "STATION_POLICY", "BROADCAST_REGULATION"]
NON_CORE_CERT_TYPES = ["UNDERWRITING_COPY"]

# --- Seniority (PRD §3.2) ---
SENIORITY = {
    "SERVICE_MONTHS_CAP": 60,
    "POINTS_PER_LIVE_CERTIFICATION": 10,
    "PERFORMANCE_WEIGHT": 0.20,
    "POINTS_PER_STRIKE": 15,
    "FLOOR": 0.00,
    "PROBATION_STRIKE_THRESHOLD": 2,
}

# --- Committee review (PRD §3.3) ---
COMMITTEE = {
    "MIN_SEATED_MEMBERS": 3,
    "QUORUM_FLOOR": 3,
    "QUORUM_FRACTION": 0.60,
    "MIN_CRITERION_SCORE": 1,
    "MAX_CRITERION_SCORE": 5,
    "WEIGHT_FORMAT_FIT": 0.40,
    "WEIGHT_DIVERSITY": 0.35,
    "WEIGHT_QUALITY": 0.25,
    "DIVERSITY_BONUS": 0.50,
    "LANGUAGE_BONUS": 0.25,
    "COMPOSITE_CAP": 5.00,
    "APPROVE_THRESHOLD": 4.00,
    "REVISION_THRESHOLD": 3.00,
    "MAX_REVIEW_ROUNDS": 2,
}

# --- Grid and slot occupation (PRD §3.4) ---
GRID = {
    "MIN_DAY_OF_WEEK": 0,
    "MAX_DAY_OF_WEEK": 6,
    "MIN_START_MINUTE": 0,
    "MAX_START_MINUTE": 1425,
    "MIN_DURATION_MINUTES": 15,
    "MAX_DURATION_MINUTES": 720,
    "MINUTES_PER_DAY": 1440,
    "WEEK_MINUTES_CAP": 10080,
    "STATION_ID_BUFFER_MINUTES": 2,
    "SENIORITY_PREEMPT_MARGIN": 5.00,
    "DIVERSITY_QUOTA_PCT": 8.00,
}

PUBLIC_AFFAIRS_FORMATS = ["PUBLIC_AFFAIRS", "NEWS"]
LIVE_SLOT_STATUSES = ["TENTATIVE", "CONFIRMED"]

# --- Airings, logs and royalties (PRD §3.5) ---
ROYALTY = {
    "RATE_CENTS_PER_MINUTE": 65,
    "FEATURED_MIN_DURATION_SECONDS": 30,
    "SURVEY_UPLIFT": 1.10,
    "LOG_DUE_HOURS": 72,
}

FEATURED_PLAY_SOURCES = ["LIBRARY_CD", "LIBRARY_VINYL", "DIGITAL"]
EXEMPT_PLAY_SOURCES = ["PRODUCTION_MUSIC"]

# --- Underwriting copy screening (PRD §3.6) ---
FLAG_WEIGHTS = {
    "CALL_TO_ACTION": 40,
    "PRICE_INFO": 35,
    "COMPARATIVE_CLAIM": 25,
    "MISSING_SPONSOR_ID": 10,
}

CALL_TO_ACTION_PHRASES = [
    "call now",
    "act now",
    "visit us today",
    "stop by today",
    "shop now",
    "limited time offer",
]
PRICE_INFO_PHRASES = ["% off", "percent off", "save $"]
COMPARATIVE_CLAIM_PHRASES = ["best", "lowest prices", "number one", "unbeatable"]

RISK_SCORE = {
    "CAP": 100,
    "APPROVE_BELOW": 25,
    "REJECT_AT_OR_ABOVE": 60,
}

PUBLIC_FILE = {
    "DUE_DAYS": 7,
}

PUBLIC_FILE_CLASSES = ["POLITICAL_CANDIDATE", "ISSUE_ADVOCACY"]

# --- Compliance incidents (PRD §3.7) ---
PENALTY_POINTS = {
    "INDECENCY": {"MINOR": 2, "MAJOR": 5, "CRITICAL": 9},
    "POLITICAL_CONTENT": {"MINOR": 1, "MAJOR": 3, "CRITICAL": 6},
    "PUBLIC_FILE": {"MINOR": 1, "MAJOR": 3, "CRITICAL": 5},
    "SPONSOR_ID": {"MINOR": 1, "MAJOR": 2, "CRITICAL": 4},
    "VOLUNTEER_CONFLICT": {"MINOR": 1, "MAJOR": 2, "CRITICAL": 4},
}

SAFE_HARBOR = {
    "START_HOUR": 6,
    "END_HOUR": 22,
    "MULTIPLIER": 2,
}

STANDING_THRESHOLDS = {
    "CLEAR_AT": 0,
    "WATCH_FROM": 1,
    "WATCH_THROUGH": 5,
    "RESTRICTED_FROM": 6,
}

SWEEP_PUBLIC_FILE_INCIDENT_POINTS = 3

# --- Performance review (PRD §3.8) ---
PERFORMANCE = {
    "WEIGHT_RELIABILITY": 0.55,
    "WEIGHT_LOG_COMPLIANCE": 0.30,
    "WEIGHT_LOCAL_SHARE": 0.15,
    "SCALE": 100,
    "PENALTY_PER_POINT": 5,
    "MIN_SCORE": 0.00,
    "MAX_SCORE": 100.00,
    "UNDERPERFORMANCE_THRESHOLD": 60.00,
    "PROBATION_THRESHOLD": 45.00,
    "TRAILING_WINDOW_SIZE": 6,
}

# --- Drives, phone banks and premiums (PRD §3.9) ---
DRIVE = {
    "MIN_GOAL_CENTS": 1,
    "MIN_PHONE_LINE_COUNT": 1,
}

# Tolerance used when comparing two-decimal PRD figures.
DECIMAL_TOLERANCE = 0.01
