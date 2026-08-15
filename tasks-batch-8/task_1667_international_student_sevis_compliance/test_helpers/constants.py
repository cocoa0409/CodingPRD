"""Domain thresholds and defaults — numeric constants from PRD calculations."""

# Logical clock startup default (PRD §2.5): the server starts at exactly
# 2026-08-01T00:00:00Z before any clock-setting call.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Financial document freshness window in days (PRD §3.1).
    "FRESHNESS_WINDOW_DAYS": 183,
    # Full-course-load floors by degree level (PRD §3.3).
    "UG_MIN_CREDITS": 12,
    "GR_MIN_CREDITS": 9,
    # ACADEMIC RCL absolute floor (PRD §3.4).
    "ACADEMIC_FLOOR_ABSOLUTE": 3,
    # MEDICAL RCL cumulative coverage cap in months (PRD §3.4).
    "MEDICAL_CUMULATIVE_MONTHS_MAX": 12,
    # Add/drop close: days after term_start_date (PRD §3.3, §3.4).
    "ADD_DROP_DAYS": 14,
    # Registration deadline: days after term_start_date (PRD §3.3).
    "REGISTRATION_DEADLINE_DAYS": 30,
    # OPT_POST unemployment limit / warning (PRD §3.5, §2.10).
    "UNEMPLOYMENT_LIMIT_DAYS": 90,
    "UNEMPLOYMENT_WARNING_DAYS": 75,
    # Address report timeliness window (PRD §3.10).
    "ADDRESS_REPORT_WINDOW_DAYS": 10,
    # Record completion grace period after program_end_date (PRD §3.9).
    "RECORD_COMPLETION_GRACE_DAYS": 60,
    # Travel endorsement validity horizons in months (PRD §3.6).
    "VALIDITY_MONTHS_ENROLLED": 12,
    "VALIDITY_MONTHS_OPT": 6,
    # Extension proration (PRD §3.8).
    "DAYS_PER_MONTH": 30,
    "MONTHS_PER_YEAR": 12,
}

TEST_DEFAULTS = {
    "SEVIS_ID": "N0012345678",
    "FULL_NAME": "Asha Rao",
    "EMAIL": "asha@example.edu",
    "DATE_OF_BIRTH": "2002-04-15",
    "COUNTRY": "IN",
    "DEGREE_LEVEL": "UNDERGRADUATE",
    "PROGRAM_START": "2026-08-24",
    "PROGRAM_END": "2027-05-31",
    "FUNDING_CENTS": 2_000_000,
    "FUNDING_ISSUE_DATE": "2026-07-01",
    "TUITION_CENTS": 1_200_000,
    "LIVING_CENTS": 600_000,
    "INSURANCE_CENTS": 120_000,
    "OTHER_CENTS": 60_000,
    "PROGRAM_NAME": "Mechanical Engineering",
    "TERM_CODE": "2026-FALL",
    "TERM_START": "2026-08-24",
    "TERM_END": "2026-12-11",
    "ENROLLED_CREDITS": 12,
}

# Second student identity used by two-student scenarios.
ALT_STUDENT = {
    "sevis_id": "N0087654321",
    "full_name": "Li Wei",
    "email": "li@example.edu",
    "date_of_birth": "2001-09-02",
    "country_of_citizenship": "CN",
    "degree_level": "GRADUATE",
}
