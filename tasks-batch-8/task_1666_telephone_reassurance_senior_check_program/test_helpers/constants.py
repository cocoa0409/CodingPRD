"""Domain thresholds and shared fixtures values — numeric constants from PRD §2-§3."""

# Logical clock default at server startup (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_ISO_3DP = "2026-08-01T00:00:00.000Z"

# 2026-08-01 is a Saturday; 2026-08-03 is a Monday (PRD §2.4 clock arithmetic).
MON_0803 = "2026-08-03"
TUE_0804 = "2026-08-04"
WED_0805 = "2026-08-05"
THU_0806 = "2026-08-06"
FRI_0807 = "2026-08-07"
MON_0810 = "2026-08-10"
TUE_0811 = "2026-08-11"
MON_0817 = "2026-08-17"
MON_0824 = "2026-08-24"
MON_0831 = "2026-08-31"

POLICY_VERSION = "v2026.1"
TRAINING_COMPLETED_AT = "2026-07-01T00:00:00Z"
TRAINING_VALID_UNTIL = "2027-08-01T00:00:00Z"
AGREEMENT_VALID_UNTIL = "2027-08-01T00:00:00Z"

THRESHOLDS = {
    # Program defaults (PRD §3.1)
    "MAX_RESERVE_SLOTS": 5,
    "NO_ANSWER_THRESHOLD": 3,
    "ESCALATION_RETRY_HOURS": 4,
    "CONTACT_PHASE_HOURS": 24,
    "OFFER_TTL_HOURS": 72,
    "REAPPLY_COOLING_DAYS": 30,
    "SURVEY_VALID_DAYS": 30,
    "DOC_BUFFER_MINUTES": 15,
    # Acuity tier bands (PRD §3.2)
    "TIER_LOW_MAX": 29,
    "TIER_MODERATE_MAX": 59,
    "TIER_HIGH_MAX": 84,
    "SCORE_CAP": 100,
    "CHRONIC_CAP": 3,
    # Reliability (PRD §3.4)
    "RELIABILITY_WINDOW_DAYS": 28,
    "RELIABILITY_MIN_HISTORY": 10,
    "STREAK_PENALTY": 5,
    "TIER_GOLD_MIN": 95.0,
    "TIER_SILVER_MIN": 80.0,
    "TIER_BRONZE_MIN": 60.0,
    # Tier concurrency caps (PRD §3.4)
    "CAP_GOLD": 12,
    "CAP_SILVER": 10,
    "CAP_BRONZE": 8,
    "CAP_PROBATION": 4,
    # Volunteer weekly minutes range (PRD §3.4)
    "MAX_WEEKLY_MINUTES_MIN": 60,
    "MAX_WEEKLY_MINUTES_MAX": 600,
    "MAX_WEEKLY_MINUTES_DEFAULT": 240,
    # Waitlist (PRD §3.3)
    "DAYS_WAITING_CAP": 30,
    "MAX_DECLINES": 2,
    "MAX_EXPIRES": 2,
    # Schedule window minutes (PRD §3.5)
    "SCHEDULE_MIN_MINUTES": 15,
    "SCHEDULE_MAX_MINUTES": 120,
    # Referral SLA hours (PRD §3.8)
    "SLA_URGENT_HOURS": 24,
    "SLA_STANDARD_HOURS": 72,
    "SLA_ROUTINE_HOURS": 168,
    # Survey shape (PRD §3.9)
    "SURVEY_ITEM_COUNT": 5,
    "SURVEY_ITEM_MIN": 1,
    "SURVEY_ITEM_MAX": 5,
}

REQUIRED_TRAINING_MODULES = ["SAFETY_PROTOCOL", "LISTENING_SKILLS", "MANDATED_REPORTING"]

# Required weekly contact counts by effective acuity tier (PRD §3.5).
REQUIRED_WEEKLY_CONTACTS = {"CRITICAL": 5, "HIGH": 3, "MODERATE": 2, "LOW": 1}

# Waitlist priority score tables (PRD §3.3).
TIER_POINTS = {"CRITICAL": 100, "HIGH": 70, "MODERATE": 40, "LOW": 10}
SOURCE_POINTS = {
    "APS_REFERRAL": 50,
    "HOSPITAL_DISCHARGE": 40,
    "OTHER_PROVIDER": 30,
    "FAMILY": 20,
    "SELF": 10,
}
LIVES_ALONE_BONUS = 15
