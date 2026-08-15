"""Domain thresholds — numeric constants from PRD workload policy defaults."""

# Workload-term policy defaults (PRD §3.1)
DEFAULTS = {
    "TERM_CODE": "2026-FA",
    "TERM_TITLE": "Fall 2026",
    "TERM_START_DATE": "2026-08-24",
    "TERM_CENSUS_DATE": "2026-09-07",
    "COMP_BUDGET_CENTS": 2_000_000,
    "BASE_TEACHING_CREDITS": 12,
    "LECTURE_MULTIPLIER": 1.0,
    "LAB_MULTIPLIER": 0.75,
    "SEMINAR_MULTIPLIER": 1.25,
    "ONLINE_PREMIUM_CREDITS": 0.5,
    "LARGE_CLASS_THRESHOLD": 40,
    "LARGE_CLASS_BONUS_CREDITS": 1.0,
    "OVERLOAD_COMP_RATE_CENTS": 150_000,
    "UNION_MAX_OVERLOAD_CREDITS": 6,
    "REASSIGNMENT_NOTICE_DAYS": 14,
    "LATE_CANCEL_STIPEND_CENTS": 100_000,
    "FLAT_RELEASE_RATE_CENTS": 80_000,
}

# Faculty defaults
FACULTY_DEFAULTS = {
    "BASE_LOAD_CREDITS": 12,
    "IS_UNION_COVERED": True,
    "BASE_SALARY_CENTS": 9_000_000,
}

# Release buyout
TERMS_PER_YEAR = 2

# Logical clock
STARTUP_CLOCK_ISO = "2026-08-01T00:00:00Z"
CENSUS_DAY_ISO = "2026-09-07T00:00:00Z"

# Standard course fixture values
COURSE_DEFAULTS = {
    "COURSE_CODE": "CS-301",
    "COURSE_TITLE": "Algorithms",
    "COURSE_TYPE": "LECTURE",
    "BASE_CREDITS": 3,
    "DEFAULT_ENROLLMENT_CAP": 30,
    "ALLOWED_MODALITIES": ["IN_PERSON", "ONLINE"],
}

# A well-formed UUID that never matches a server-minted id in a fresh database
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
