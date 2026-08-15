"""Domain thresholds — numeric constants from the PRD."""

# Canonical logical-clock dates used across the suite.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"   # startup clock per PRD
CLOCK_TODAY = "2026-08-20T00:00:00Z"     # canonical "today" for most tests
TODAY = "2026-08-20"

THRESHOLDS = {
    # cut-score bands for the canonical P_BAND profile
    "P_BAND_CUT": 95,
    "P_BAND_FLOOR": 88,
    "P_BAND_CUT_2E": 90,
    "P_BAND_FLOOR_2E": 82,
    # committee quorum
    "COMMITTEE_SEATS": 3,
    "QUALIFY_THRESHOLD": 2,
    "DENY_THRESHOLD": 2,
    # re-evaluation exit-score bands
    "RETAIN_FLOOR": 70.0,
    "PROBATION_FLOOR": 50.0,
    "GROWTH_WEIGHT": 0.5,
    "SERVICE_WEIGHT": 7.5,
    "TEACHER_WEIGHT": 4.0,
    # temporal windows (days)
    "TRANSFER_HONOR_WINDOW_DAYS": 45,
    "APPEAL_WINDOW_DAYS": 30,
    "OFFER_ACCEPT_WINDOW_DAYS": 30,
    "EXTERNAL_ID_MAX_AGE_DAYS": 730,
    "MEASURE_VALIDITY_DEFAULT_DAYS": 730,
    # disproportionality report
    "FLAG_THRESHOLD": 0.800,
    "MIN_CELL": 10,
}

# Canonical cycle window: half-open [2026-08-15, 2026-12-15), referral close 2026-09-30.
CYCLE_WINDOW = {
    "screening_open_on": "2026-08-15",
    "screening_close_on": "2026-12-15",
    "referral_close_on": "2026-09-30",
}
