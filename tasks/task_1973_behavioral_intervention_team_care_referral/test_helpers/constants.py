"""Domain thresholds — numeric constants from the PRD (§3.2, §3.4, §3.5, §3.8)."""

# PRD §3.2 triage rubric weights and tier thresholds.
RUBRIC = {
    "W_SELF": 0.35,
    "W_OTHERS": 0.35,
    "W_ACADEMIC": 0.15,
    "W_SUBSTANCE": 0.15,
    "SCALE": 4,
    "REASSESS_NEW_WEIGHT": 0.6,
    "REASSESS_PREV_WEIGHT": 0.4,
    "DIMENSION_MIN": 0,
    "DIMENSION_MAX": 25,
}

TIER_THRESHOLDS = {
    "IMMINENT": 80,
    "HIGH": 60,
    "MODERATE": 30,
}

# PRD §3.4 follow-up cadence (days) keyed by current risk tier.
CADENCE_DAYS = {
    "IMMINENT": 2,
    "HIGH": 7,
    "MODERATE": 14,
    "LOW": 30,
}

# PRD §2.5 / §3.4: MISSED fires when now > due_at + 1 full day.
MISSED_GRACE_DAYS = 1

# PRD §3.6: the first post-re-entry check-in is fixed at exactly seven days.
REENTRY_FIRST_CHECKIN_DAYS = 7

# PRD §3.2: IMMINENT auto-grants expire exactly 72 hours after creation.
AUTO_GRANT_TTL_HOURS = 72

# PRD §3.8: closure requires at least three consecutive STABLE check-ins.
MIN_CONSECUTIVE_STABLE = 3

# PRD §3.5: assessment due_at window — strictly later than now, at most 14 days out.
ASSESSMENT_MAX_DUE_DAYS = 14

# PRD §2.5: server startup logical-clock default.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Category order pinned by PRD §3.8 for the distribution rounding order.
CATEGORY_ORDER = [
    "ACADEMIC_DISTRESS",
    "BEHAVIORAL_THREAT",
    "SELF_HARM_RISK",
    "SUBSTANCE_CONCERN",
    "WELLBEING_GENERAL",
]
