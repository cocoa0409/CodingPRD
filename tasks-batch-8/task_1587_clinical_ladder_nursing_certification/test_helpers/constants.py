"""Domain thresholds — numeric constants stated in the PRD.

All values come from PRD prose (§2.3, §2.5, §3.2-§3.7).
"""

# Logical clock default at server start (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Participation window (PRD §3.2)
    "LOOKBACK_MONTHS": 24,
    "POINTS_MIN": 1,
    "POINTS_MAX": 40,
    "COMMITTEE_SEAT_POINTS_MAX": 20,
    # Committee scoring (PRD §3.4)
    "QUORUM": 3,
    "REVIEW_WINDOW_DAYS": 14,
    "REVIEW_CYCLE_CAP": 3,
    # Reimbursement cap (PRD §3.3)
    "NURSE_FY_REIMBURSEMENT_CAP_CENTS": 150000,
    # Certification bonus tiers (PRD §3.3)
    "BONUS_BASIC_CENTS": 50000,
    "BONUS_SPECIALTY_CENTS": 100000,
    "BONUS_ADVANCED_CENTS": 175000,
    "TENURE_BONUS_CENTS": 25000,
    "TENURE_BONUS_YEARS": 10,
    # Maintenance score (PRD §3.5)
    "MAINTENANCE_THRESHOLD": 60,
    "PARTICIPATION_CAP": 40,
    "TENURE_CAP": 20,
    # Retention risk bumps (PRD §3.7)
    "RISK_DECAY_PER_YEAR": 10,
    "RISK_DEMOTION_BUMP": 15,
    "RISK_CERT_LAPSE_BUMP": 10,
    "RISK_DENIAL_BUMP": 8,
    "RISK_CLAWBACK_BUMP": 5,
    "RISK_VERIFIED_EVENT_DELTA": -6,
    "RISK_ADVANCEMENT_DELTA": -20,
    "RISK_CAP_MAX": 100,
    "RISK_CAP_MIN": 0,
    # Budget forecast (PRD §3.6)
    "PIPELINE_YIELD": 0.80,
    # Pagination (PRD §2.3)
    "PAGE_LIMIT_DEFAULT": 10,
    "PAGE_LIMIT_MIN": 1,
    "PAGE_LIMIT_MAX": 100,
}

# Committee score dimension weights (PRD §3.4).
SCORE_WEIGHTS = {
    "leadership": 0.30,
    "clinical_expertise": 0.30,
    "professional_development": 0.20,
    "outcomes": 0.20,
}

TEST_DEFAULTS = {
    "HOME_UNIT": "MED-2E",
    "ALT_UNIT": "ICU-4W",
    "HIRE_DATE": "2020-01-01T00:00:00Z",
    "CRITERION_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "MIN_PORTFOLIO_SCORE": 75,
    "DIFFERENTIAL_CN_II_CENTS": 30000,
    "DIFFERENTIAL_CN_III_CENTS": 50000,
    "EXAM_FEE_CENTS": 40000,
    "BUDGET_ALLOCATED_CENTS": 9000000,
}
