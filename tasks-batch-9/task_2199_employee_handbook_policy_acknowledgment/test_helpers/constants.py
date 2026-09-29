"""Numeric thresholds and constants stated by the PRD's computations."""

# PRD §2.5 — the logical clock reads exactly this at server startup.
CLOCK_START = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.5 accessibility bands
    "A11Y_AA_FLOOR": 90.00,
    "A11Y_AAA_FLOOR": 96.00,
    "A11Y_ACCESSIBLE_MIN": 96.00,
    # PRD §3.7 acknowledgment-deadline clamps
    "ON_LEAVE_EXTRA_DAYS": 14,
    "ACCESSIBLE_FLOOR_DAYS": 21,
    "SAFETY_CAP_DAYS": 7,
    # PRD §3.8 escalation tier ladder
    "TIER_2_MIN_DAYS_OVERDUE": 7,
    "TIER_3_MIN_DAYS_OVERDUE": 14,
    "TIER_MAX": 3,
    # PRD §3.9 exception risk
    "EXCEPTION_RISK_CEILING": 70.00,
    "DURATION_REFERENCE_DAYS": 180,
    "HISTORY_FACTOR_PER_PRIOR": 30,
    "FACTOR_CAP": 100,
    # PRD §3.6 legal-review-deadline buffers
    "BUFFER_DAYS_NO_SLACK": 7,
    "BUFFER_DAYS_MID_SLACK": 3,
    "BUFFER_DAYS_AMPLE_SLACK": 1,
    # PRD §3.7 retention dispute floor
    "RETENTION_DISPUTE_FLOOR_DAYS": 1095,
}

# PRD §3.9 — the reason factor lookup on reason_code.
REASON_FACTOR = {
    "RELIGIOUS": 20,
    "MEDICAL": 25,
    "COLLECTIVE_BARGAINING": 45,
    "ROLE_CONFLICT": 65,
}

# PRD §3.9 — the category factor lookup on the owning document's category.
CATEGORY_FACTOR = {
    "SAFETY": 90,
    "DATA_PRIVACY": 75,
    "COMPENSATION": 55,
    "CODE_OF_CONDUCT": 40,
    "LEAVE": 25,
}

# PRD §3.9 — the weighted mean weights.
RISK_WEIGHTS = {
    "reason": 0.20,
    "duration": 0.15,
    "history": 0.25,
    "category": 0.40,
}
CONSERVATIVE_PEAK_WEIGHT = 0.60
CONSERVATIVE_MEAN_WEIGHT = 0.40

TEST_DEFAULTS = {
    "MIN_LEGAL_REVIEW_DAYS": 0,
    "ACK_DEADLINE_DAYS": 30,
    "RETENTION_YEARS": 5,
    "ACK_WINDOW_BUFFER_DAYS": 3,
    "MAX_ACK_DEADLINE_DAYS": 30,
    "SECTION_COUNT": 2,
}
