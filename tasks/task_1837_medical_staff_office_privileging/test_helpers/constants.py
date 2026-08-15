"""Domain thresholds and fixed instants — numeric constants stated in PRD prose.

Note: the hearing-request window length is described in PRD §3.8 only as "a
fixed number of days configured for the installation" — no value is stated —
so tests must read `hearing_request_deadline` back from the case rather than
assume a number of days.
"""

# Logical clock (PRD §2.5): fixed startup default.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Delineation satisfaction scoring (PRD §3.3).
TRAINING_BONUS_CAP_MONTHS = 24
TRAINING_BONUS_PER_MONTH = 0.5
CASE_SCORE_CAP = 1000

# Review outcome thresholds (PRD §3.5).
SATISFACTORY_MIN = 70.00
MARGINAL_MIN = 50.00

# Credential expiry risk (PRD §3.6).
RISK_SUSPEND_THRESHOLD = 75.00
WINDOW_30D_PTS = 50
WINDOW_90D_PTS = 25
LAPSED_PTS = 100
CRITICAL_KIND_MULTIPLIER = 1.5

# Appointment term & reappointment window (PRD §3.4).
TERM_YEARS = 2
REAPPOINTMENT_WINDOW_DAYS = 180

# NPDB reporting window (PRD §3.8): thirty days from the triggering event.
NPDB_REPORT_WINDOW_DAYS = 30

# Quorums (PRD §3.4, §3.8).
COMMITTEE_QUORUM = 3
MIN_HEARING_QUORUM = 3

# Temporary-privilege window caps (PRD §3.7).
EMERGENCY_CAP_HOURS = 24
DISASTER_CAP_HOURS = 72
TEMPORARY_CAP_DAYS = 120

# Default specialty criteria parameters used across scenarios.
DEFAULT_SPECIALTY = {
    "specialty_code": "EMED",
    "privilege_line": "EMED-GEN",
    "min_training_months": 12,
    "min_case_volume_24mo": 10,
    "required_board_cert": False,
    "fppe_case_count": 1,
    "volume_tier_table": [
        {"tier_name": "BASIC", "min_cases": 10, "score_multiplier": 0.10},
    ],
}

# Cardiology catheterization criteria used by the delineation scoring tests.
CARD_CATH_CRITERIA = {
    "specialty_code": "CARD",
    "privilege_line": "CARD-CATH",
    "min_training_months": 24,
    "min_case_volume_24mo": 50,
    "required_board_cert": True,
    "fppe_case_count": 5,
    "volume_tier_table": [
        {"tier_name": "BASIC", "min_cases": 50, "score_multiplier": 0.10},
        {"tier_name": "ADVANCED", "min_cases": 200, "score_multiplier": 0.25},
        {"tier_name": "EXPERT", "min_cases": 500, "score_multiplier": 0.40},
    ],
}

# Surgery criteria used by the credential-lapse cascade tests.
SURG_GENERAL_CRITERIA = {
    "specialty_code": "SURG",
    "privilege_line": "SURG-GENERAL",
    "min_training_months": 24,
    "min_case_volume_24mo": 20,
    "required_board_cert": True,
    "fppe_case_count": 1,
    "volume_tier_table": [
        {"tier_name": "BASIC", "min_cases": 20, "score_multiplier": 0.10},
    ],
}

# Default review measurement window (half-open [start, end)).
REVIEW_PERIOD_START = "2026-09-01T00:00:00Z"
REVIEW_PERIOD_END = "2026-10-01T00:00:00Z"
