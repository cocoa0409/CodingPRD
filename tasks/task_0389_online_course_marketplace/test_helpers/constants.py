"""Domain thresholds and default test values (PRD §3).

Generic NON_EXISTENT_UUID comes from the framework barrel export.
"""

# Course creation defaults (PRD §3.2).
COURSE_DEFAULTS = {
    "PASSING_SCORE_PCT": 0.70,
    "REFUND_WINDOW_DAYS": 30,
    "DRIP_ENABLED": False,
    "CEU_CREDITS": 0.0,
    "COMPLETION_THRESHOLD_PCT": 1.00,
}

# Instructor creation default (PRD §3.1).
INSTRUCTOR_DEFAULTS = {
    "REVENUE_SHARE_PCT": 0.50,
}

# Bundle-enrollment promotional-window buffer (PRD §3.6): one full day.
BUNDLE_PROMO_BUFFER_SECONDS = 86_400

# A well-formed UUID that resolves to no resource (for 404 tests).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
