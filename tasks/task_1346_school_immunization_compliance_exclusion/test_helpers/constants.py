"""Domain thresholds and shared test values (PRD sections 2.4, 2.10, 3.1, 3.5, 3.7)."""

THRESHOLDS = {
    # PRD 3.1: "a provisional window of 30 days from enrollment"
    "PROVISIONAL_WINDOW_DAYS": 30,
    # PRD 3.5: "the exclusion date is the issue date plus 14 days"
    "EXCLUSION_GRACE_DAYS": 14,
    # PRD 3.7: "no new session may begin less than 7 days from an existing session"
    "MIN_SESSION_GAP_DAYS": 7,
    # PRD 2.10: rates "rounded to exactly 1 decimal place using the round-half-up method"
    "RATE_DECIMALS": 1,
}

# PRD 2.4: "the logical clock reads exactly `2026-08-01T00:00:00Z`" at startup.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
SCHOOL_YEAR_DEFAULT = "2026-2027"

TEST_DEFAULTS = {
    "DATE_OF_BIRTH": "2020-06-15T00:00:00Z",
    "ENROLLMENT_DATE": "2026-08-01T00:00:00Z",
    "GRADE": "K",
    "VACCINE_CODE": "MMR",
    "DOSES_REQUIRED": 1,
    "MIN_INTERVAL_DAYS": 0,
    "MIN_AGE_MONTHS": 12,
    "CENSUS_DATE": "2026-10-01T00:00:00Z",
    "SESSION_DATE": "2026-09-01T09:00:00Z",
}
