"""Domain thresholds — numeric constants from PRD calculations."""

# ─── Priority score weights (PRD §3.5) ───────────────────────────────
PRIORITY_WEIGHTS = {
    "W_YEAR": 10,
    "W_GAP": 15,
    "W_PREREQ": 8,
    "W_FRAUD": 2,
    "FRAUD_GRACE": 10,
    "YEAR_FACTOR_CAP": 5,
}

# ─── Dynamic credit quota tiers (PRD §3.6) ───────────────────────────
CREDIT_QUOTA_TIERS = {
    1: 18.0,
    2: 20.0,
    3: 22.0,
    4: 24.0,
    5: 24.0,
    6: 24.0,
}

# ─── Anti-fraud constants (PRD §2.11) ────────────────────────────────
FRAUD = {
    "RAPID_SUBMIT_WINDOW_SECONDS": 60,
    "RAPID_SUBMIT_LIMIT": 10,
    "RAPID_SUBMIT_PENALTY": 5,
    "UNAUTHORIZED_DEPT_PENALTY": 8,
}

# ─── Recommendation weights (PRD §3.8) ───────────────────────────────
RECOMMENDATION_WEIGHTS = {
    "REC_W_GAP": 100,
    "REC_W_PREREQ_UNLOCK": 30,
    "REC_W_TIME_CONFLICT": 50,
    "REC_TOP_K": 5,
}

# ─── Numeric precision (PRD §2.5) ────────────────────────────────────
CREDIT_DECIMAL_PLACES = 2

# ─── Pagination limits (PRD §2.3) ────────────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# ─── Downstream sync targets (PRD §2.12) ─────────────────────────────
SYNC_TARGETS = {
    "ENROLLMENT_APPROVED": ["ACADEMIC_AFFAIRS", "FINANCE", "LIBRARY", "DORMITORY"],
    "ENROLLMENT_CANCELED": ["ACADEMIC_AFFAIRS", "FINANCE", "LIBRARY", "DORMITORY"],
    "TUITION_BILLED": ["FINANCE"],
    "TUITION_PAID": ["FINANCE", "LIBRARY", "DORMITORY"],
    "OVER_LIMIT_GRANTED": ["ACADEMIC_AFFAIRS", "FINANCE"],
    "CAPACITY_REDUCED_CANCELED": ["ACADEMIC_AFFAIRS", "FINANCE", "LIBRARY", "DORMITORY"],
    "WAITLIST_PROMOTED": ["ACADEMIC_AFFAIRS", "FINANCE", "LIBRARY", "DORMITORY"],
}

# ─── Common defaults used across factories ───────────────────────────
DEFAULTS = {
    "TERM_DURATION_SECONDS": 86_400 * 120,         # 120 days
    "REGISTRATION_DURATION_SECONDS": 86_400 * 30,  # 30 days
    "CLASSES_DURATION_SECONDS": 86_400 * 60,       # 60 days
    "EXAM_WEEK_DURATION_SECONDS": 86_400 * 7,      # 7 days
    "BASE_CAPACITY": 10,
    "DEFAULT_CREDITS": 3.0,
    "DEFAULT_TEACHING_MINUTES_CAP": 600,
}
