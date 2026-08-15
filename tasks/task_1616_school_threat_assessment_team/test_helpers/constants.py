"""Domain thresholds and scoring constants from the PRD."""

# Logical clock: server startup default (PRD logical-clock section).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# Screening instrument (PRD initial-screening section).
SCREENING_FACTOR_KEYS = (
    "threat_of_violence",
    "weapon_mention",
    "target_identified",
    "plan_described",
    "prior_incidents",
    "current_distress",
)
SCREENING_SUBSTANTIVE_MIN_SCORE = 3

# Risk assessment scoring (PRD risk-assessment section).
FACTOR_WEIGHTS = {
    "WEAPON_ACCESS": 20,
    "PLAN_SPECIFICITY": 15,
    "GRIEVANCE_HISTORY": 10,
    "BEHAVIORAL_ESCALATION": 10,
    "SUPERVISION_GAP": 8,
    "PEER_REPORTS": 5,
}
CRITICAL_BONUS_STANDARD = 10
CRITICAL_BONUS_EXPEDITED = 15
EXPEDITED_MULTIPLIER_NUM = 3  # one and a half, as a ratio of integers
EXPEDITED_MULTIPLIER_DEN = 2
SCORE_CLAMP_MIN = 0
SCORE_CLAMP_MAX = 100

# Risk-level band boundaries (PRD risk-assessment section).
RISK_LEVEL_MODERATE_MIN = 20
RISK_LEVEL_HIGH_MIN = 40
RISK_LEVEL_IMMINENT_MIN = 60

# Monitoring cadence tables (PRD management-plan section).
CADENCE_DEFAULT_BY_LEVEL = {"IMMINENT": 3, "HIGH": 7, "MODERATE": 14, "LOW": 30}
CADENCE_MAX_BY_LEVEL = {"IMMINENT": 7, "HIGH": 14, "MODERATE": 30, "LOW": 60}

# Interview protocol (PRD interview section).
MAX_INTERVIEWS_PER_CASE = 8

# Miss escalation (PRD management-plan section).
CONSECUTIVE_MISS_ESCALATION_THRESHOLD = 2

# Re-entry monitoring (PRD removal/re-entry section).
REENTRY_CHECKIN_OFFSET_DAYS = 30

# Referral SLAs (PRD referral section).
URGENT_SLA_HOURS = 72
ROUTINE_SLA_HOURS = 240
AUTO_REFERRAL_AGENCY = "DISTRICT_SRT"

# Records retention (PRD retention section).
DEFAULT_RETENTION_DAYS = 365
MIN_RETENTION_DAYS = 30

# Alias written over subject_alias by the retention purge.
PURGED_ALIAS = "PURGED"
