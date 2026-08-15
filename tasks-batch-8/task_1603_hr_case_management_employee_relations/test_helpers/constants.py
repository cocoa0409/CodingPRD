"""Domain thresholds and constants from PRD §3."""

# Credibility score (PRD §3.4)
CREDIBILITY = {
    "BASE": 0.50,
    "CORRO_W_C": 0.10,
    "CONTRA_W_C": 0.15,
    "CORRO_W_R": 0.06,
    "CONTRA_W_R": 0.10,
    "RECENCY_DECAY_PER_DAY": 0.005,
    "CORRO_CAP": 4,
    "CONTRA_CAP": 3,
    "AGE_CAP_DAYS": 60,
    "SUBSTANTIATION_GATE": 0.50,
}

# Action calibration (PRD §3.5)
CALIBRATION = {
    "FALLBACK_MEDIAN_LOW": 10,
    "FALLBACK_MEDIAN_MEDIUM": 30,
    "FALLBACK_MEDIAN_HIGH": 60,
    "FALLBACK_MEDIAN_CRITICAL": 85,
    "HISTORY_WINDOW_DAYS": 365,
    "MIN_HISTORY_FOR_MEDIAN": 3,
    "QUORUM": 2,
}

# Trend rate (PRD §3.7)
TREND = {
    "ROLLING_WINDOW_DAYS": 90,
    "RATE_MULTIPLIER": 100,
}

# SLA business-day arithmetic (PRD §3.2)
SLA = {
    "BUSINESS_DAY_END_HOUR_UTC": 17,
}

# Documentation minimums (PRD §3.x)
DOCUMENTATION = {
    "INTERVIEW_MIN_CHARS": 50,
    "FINDING_MIN_CHARS": 100,
    "ACTION_MIN_CHARS": 30,
    "REOPEN_MIN_CHARS": 30,
    "REJECTION_MIN_CHARS": 20,
    "EXCLUSION_MIN_CHARS": 20,
    "HOLD_MIN_CHARS": 20,
    "RELEASE_AUTHORITY_MIN_CHARS": 8,
}

# Reopen cap (PRD §3.6)
REOPEN_LIMIT = 2

# No-show grace window minutes (PRD §3.3)
NO_SHOW_GRACE_MINUTES = 30
