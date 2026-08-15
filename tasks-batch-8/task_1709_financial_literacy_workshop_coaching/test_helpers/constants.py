"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # No-show strike limit: reaching 3 flips ACTIVE -> RESTRICTED (PRD §3.3).
    "NO_SHOW_LIMIT": 3,
    # Participant travel buffer applied on both ends of each existing workshop (PRD §3.2).
    "TRAVEL_BUFFER_MINUTES": 30,
    # Referral lifetime in days: expires_at = sent_at + 30d (PRD §3.8).
    "REFERRAL_TTL_DAYS": 30,
    # Coach certification validity in days (PRD §3.5).
    "CERTIFICATION_VALIDITY_DAYS": 365,
    # Credit-score range bounds (PRD §2.7, §3.4, §3.6).
    "CREDIT_SCORE_MIN": 300,
    "CREDIT_SCORE_MAX": 850,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK": "2026-08-01T00:00:00Z",
    "MODULE_CODE": "BF-101",
    "MODULE_TITLE": "Budgeting Basics",
    "SESSION_COUNT": 4,
    "INCENTIVE_CENTS_PER_HOUR": 500,
    "COMPLETION_BONUS_CENTS": 1000,
    "COMPLETION_THRESHOLD": 2,
    "COACH_NAME": "Test Coach",
    "COACH_MAX_CASELOAD": 10,
    "PARTICIPANT_NAME": "Test Participant",
    "ANNUAL_INCOME_CENTS": 2000000,
    "WORKSHOP_LOCATION": "Room A",
    "WORKSHOP_CAPACITY": 10,
    "INTAKE_DATE": "2026-08-01",
    "MONTHLY_SAVINGS_GOAL_CENTS": 20000,
    "CREDIT_SCORE_TARGET": 700,
    "POOL_NAME": "Match Pool",
    "POOL_TOTAL_FUNDED_CENTS": 1000000,
    "POOL_INCOME_THRESHOLD_CENTS": 3000000,
    "POOL_MATCH_RATIO_BELOW": 0.5,
    "POOL_MATCH_RATIO_ABOVE": 0.25,
    "POOL_PER_PARTICIPANT_CAP_CENTS": 100000,
    "ENROLLMENT_SAVINGS_GOAL_CENTS": 500000,
    "PARTNER_NAME": "Community Bank",
    "PARTNER_TYPE": "LENDER",
}
