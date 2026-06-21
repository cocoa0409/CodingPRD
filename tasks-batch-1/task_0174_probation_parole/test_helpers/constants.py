"""Domain thresholds and constants from the PRD's calculations.

These mirror the numeric rules stated in PRD §3 (LSI-R bands, sanction matrix,
violation points, early-termination threshold).
"""

# LSI-R actuarial band boundaries (PRD §3.2).
# total <= 13 -> ADMINISTRATIVE; 14..23 -> MINIMUM; 24..33 -> MEDIUM; 34..54 -> MAXIMUM.
LSI_R_BANDS = {
    "ADMIN_MAX": 13,
    "MINIMUM_MAX": 23,
    "MEDIUM_MAX": 33,
    "TOTAL_MAX": 54,
}

# The ten LSI-R domain keys (PRD §3.2), in scaffold order.
LSI_R_DOMAINS = [
    "criminal_history",
    "education_employment",
    "financial",
    "family_marital",
    "accommodation",
    "leisure_recreation",
    "companions",
    "alcohol_drug",
    "emotional_personal",
    "attitudes_orientation",
]

# Supervision-level ordering (PRD §2.7): ADMINISTRATIVE < MINIMUM < MEDIUM < MAXIMUM.
LEVEL_ORDER = {
    "ADMINISTRATIVE": 0,
    "MINIMUM": 1,
    "MEDIUM": 2,
    "MAXIMUM": 3,
}

# Violation point values by class (PRD §3.5).
VIOLATION_POINTS = {
    "TECHNICAL": 2,
    "MISDEMEANOR": 4,
    "FELONY": 6,
    "ABSCOND": 12,
}

# Sanction-matrix tier boundaries (PRD §3.5).
SANCTION_TIERS = {
    "TIER1_MAX": 4,
    "TIER2_MAX": 8,
    "TIER3_MAX": 11,
}

# Revocation-referral threshold (PRD §3.5 / §3.7 / §3.8): cumulative >= 12.
REVOCATION_REFERRAL_THRESHOLD = 12

# Jail-shock day formula (PRD §3.5): imposed_days = (cumulative - 9) * 2 in tier 3.
JAIL_BASE_DAYS = 0
JAIL_STEP_DAYS = 2

# Early-termination minimum percent of term served (PRD §3.9): >= 50.
EARLY_TERM_MIN_PERCENT = 50

# Default check-in on-time window length in minutes (PRD §3.4).
DEFAULT_WINDOW_MINUTES = 60

TEST_DEFAULTS = {
    "ORDERED_TERM_MONTHS": 24,
    "SENTENCE_STATE_CODE": "CA",
    "SUPERVISION_START_DATE": "2025-01-01T00:00:00.000Z",
}
