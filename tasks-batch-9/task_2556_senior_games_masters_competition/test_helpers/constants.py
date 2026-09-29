"""Numeric constants and shared fixture literals taken from the PRD."""

# The logical clock reads exactly this instant on process startup (PRD §2.4).
CLOCK_EPOCH_UTC = "2026-08-01T00:00:00Z"

# Age band assignment (PRD §3.2)
MIN_ELIGIBLE_AGE = 50
BAND_WIDTH_YEARS = 5
OPEN_BAND_FLOOR = 100
OPEN_BAND_CODE = "100+"
AGE_EXEMPTION_FLOOR = 75

# Registration fee settlement (PRD §3.2)
BASE_REGISTRATION_FEE_CENTS = 9500
SURCHARGE_LOW_THRESHOLD_CENTS = 25000
SURCHARGE_HIGH_THRESHOLD_CENTS = 60000
ADMIN_SURCHARGE_LOW_CENTS = 1500
ADMIN_SURCHARGE_HIGH_CENTS = 4000

# Medical risk score (PRD §3.4)
AGE_POINT_FLOOR = 55
AGE_POINTS_PER_YEAR = 1.5
AGE_POINT_CAP = 30
BP_POINTS_ELEVATED = 12
BP_POINTS_HIGH = 25
HR_POINT_FLOOR = 70
HR_POINTS_PER_BPM = 0.4
LOAD_POINTS_PER_CONTACT_ENTRY = 7
LOAD_POINT_CAP = 20
CARDIAC_MULTIPLIER = 1.6
RESTRICTION_THRESHOLD = 25.0
HOLD_THRESHOLD = 60.0
RISK_SCORE_CEILING = 100.0

# Scheduling and staffing (PRD §3.5, §3.6)
DEFAULT_TEARDOWN_BUFFER_MINUTES = 15
DEFAULT_REQUIRED_OFFICIAL_COUNT = 2
PERSONNEL_TRAVEL_BUFFER_MINUTES = 45
MAX_DAILY_ASSIGNED_MINUTES = 480
ATHLETE_RECOVERY_GAP_MINUTES = 30
EMERGENCY_PROTOCOL_BAND_FLOOR = 75

# Revision / protest budgets (PRD §3.3, §3.7)
MAX_REVISION_ROUNDS = 2
MAX_PROTEST_ROUNDS = 1

# Sponsorship recognition (PRD §3.9)
BUCKET_WEIGHTS = {
    "VENUE_SIGNAGE": 0.4,
    "ATHLETE_SERVICES": 0.3,
    "MEDICAL_COVERAGE": 0.2,
    "SOCIAL_PROGRAM": 0.1,
}
TIER_MULTIPLIERS = {
    "BRONZE": 1.0,
    "SILVER": 1.05,
    "GOLD": 1.12,
    "PLATINUM": 1.25,
}

# Economic impact (PRD §3.9)
ACCOMPANYING_VISITOR_FACTOR = 1.8
PROJECTED_NIGHTS_PER_ATHLETE = 4
DAILY_SPEND_CENTS = 18500
ECONOMIC_MULTIPLIER = 1.45

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Shared fixture literals.  The reference edition calendar used throughout the
# suite: competition 2026-09-10 .. 2026-09-20, age reference 2026-12-31,
# registration deadline 2026-08-25T23:59:59Z.  Its village window is therefore
# 2026-09-08 .. 2026-09-22.
# ---------------------------------------------------------------------------
EDITION_START_DATE = "2026-09-10"
EDITION_END_DATE = "2026-09-20"
EDITION_AGE_REFERENCE_DATE = "2026-12-31"
EDITION_REGISTRATION_DEADLINE_UTC = "2026-08-25T23:59:59Z"
VILLAGE_WINDOW_OPEN_DATE = "2026-09-08"
VILLAGE_WINDOW_CLOSE_DATE = "2026-09-22"

# An athlete born on this date is 60 at the reference date and 60 on the first
# competition day, so they land in the 60-64 band under either age basis.
DOB_AGE_60 = "1966-03-02"
BAND_60_64 = "60-64"

# Operator identifier strings for the five opaque roles.
ADMIN_USER_ID = "ga-hollis"
REGISTRATION_OFFICER_USER_ID = "ro-diaz"
MEDICAL_DIRECTOR_USER_ID = "md-lopez"
RECORDS_RATIFIER_USER_ID = "rr-kane"
SPONSOR_LIAISON_USER_ID = "sl-marks"
