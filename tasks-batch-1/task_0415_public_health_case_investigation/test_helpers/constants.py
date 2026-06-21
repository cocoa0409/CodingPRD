"""Domain thresholds — numeric constants from the PRD's scoring and date rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Contact priority score weights (PRD §3.6)
PRIORITY_SCORE = {
    "BASE": {
        "HOUSEHOLD": 50,
        "HEALTHCARE": 40,
        "WORKPLACE": 25,
        "SOCIAL": 15,
        "COMMUNITY": 10,
    },
    "PROX_NEAR_BONUS": 20,      # proximity_meters < 1
    "PROX_MID_BONUS": 10,       # proximity_meters <= 2 (and >= 1)
    "DUR_HIGH_BONUS": 15,       # cumulative_exposure_minutes >= 15
    "DUR_HIGH_MIN": 15,
    "DUR_MID_BONUS": 5,         # cumulative_exposure_minutes >= 5 (and < 15)
    "DUR_MID_MIN": 5,
    "VULN_BONUS": 20,           # is_high_risk_contact
    "BAND_HIGH": 70,            # priority_score >= 70 -> HIGH
    "BAND_MEDIUM": 40,          # priority_score >= 40 -> MEDIUM
    "SCORE_FLOOR": 0,
    "SCORE_CEILING": 100,
}

# Case completeness score weights (PRD §3.5)
COMPLETENESS_SCORE = {
    "W_INTERVIEW": 40,
    "W_WINDOW": 20,
    "W_CONTACTS": 20,
    "W_LAB": 20,
}

# Outbreak cluster defaults (PRD §3.1 / §3.11)
CLUSTER = {
    "MIN_CASES_DEFAULT": 3,
    "WINDOW_DAYS_DEFAULT": 14,
}

# Default deterministic surveillance clock at program creation (PRD §2.4)
DEFAULT_CLOCK = "2026-01-01T00:00:00.000Z"

# A standard COVID19 condition config reused by most fixtures.
DEFAULT_CONDITION = {
    "condition_code": "COVID19",
    "display_name": "COVID-19",
    "presymptomatic_days": 2,
    "infectious_tail_days": 10,
    "quarantine_days": 14,
    "test_based_release_days": 7,
    "test_release_earliest_offset_days": 5,
    "isolation_min_days": 5,
    "fever_free_days": 1,
}
