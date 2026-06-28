"""Domain thresholds — numeric constants from PRD calculations and defaults."""

# Pagination defaults (PRD §2.3)
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# Center default pricing knobs (PRD §3.1)
CENTER_DEFAULTS = {
    "INSTRUCTOR_RATIO_CAP": 6,
    "ENROLLMENT_FEE_CENTS": 5000,
    "MONTHLY_TUITION_CENTS": 15000,
}

# FranchiseAgreement default royalty terms (PRD §3.1)
AGREEMENT_DEFAULTS = {
    "ROYALTY_RATE_BPS": 1000,
    "MARKETING_FEE_BPS": 200,
    "MINIMUM_MONTHLY_ROYALTY_CENTS": 50000,
    "ROYALTY_BASIS": "ROYALTY_FLOOR",
    "BPS_DENOM": 10000,
}

# CurriculumLevel defaults (PRD §3.2)
LEVEL_DEFAULTS = {"WORKSHEETS_TO_MASTER": 10, "MASTERY_SCORE_THRESHOLD": 80}

# Tuition discount tiers (PRD §3.6)
DISCOUNTS = {
    "MULTI_SUBJECT_2": 0.10,
    "MULTI_SUBJECT_3PLUS": 0.15,
    "SIBLING_2": 0.05,
    "SIBLING_3PLUS": 0.10,
}

# Session / scheduling (PRD §3.5)
INSTRUCTOR_BUFFER_MINUTES = 30

# Diagnostic placement (PRD §3.3)
MAX_DIAGNOSTIC_SCORE = 100

# Server startup clock default (PRD §2.9)
CLOCK_STARTUP_DEFAULT = "2026-04-01T00:00:00Z"
