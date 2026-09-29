"""Numeric and textual constants declared by the PRD.

Every value here is quoted directly from the PRD; nothing is inferred.
"""

API_PREFIX = "/compliance"

# ---------------------------------------------------------------------------
# Logical clock (PRD: "Every server-side timestamp is read from a logical
# clock that starts at 2026-08-01T00:00:00Z")
# ---------------------------------------------------------------------------

CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Calling window arithmetic
# ---------------------------------------------------------------------------

MINUTES_PER_DAY = 1440
FEDERAL_FLOOR_MINUTES = 480
FEDERAL_CEILING_MINUTES = 1260
NON_WRITTEN_CONSENT_EXTENSION_MINUTES = 60
SMS_NARROWING_MINUTES = 30

# ---------------------------------------------------------------------------
# Abandonment measurement and dialer pacing
# ---------------------------------------------------------------------------

MIN_MEASURED_LIVE_ANSWERS = 2
REGULATORY_ABANDONMENT_CEILING_PCT = 3.00
PACING_HEADROOM_CAP_PCT = 2.00
PACING_GAIN_PER_PCT = 0.25
ROLLING_WINDOW_DAYS = 7

# ---------------------------------------------------------------------------
# Complaint risk scoring and statutory exposure
# ---------------------------------------------------------------------------

SOURCE_WEIGHT = {
    "DIRECT": 1.0,
    "STATE_AG": 1.25,
    "FTC": 1.5,
    "LITIGATION": 2.0,
}
VIOLATION_WEIGHT = {
    "NO_CONSENT": 1.5,
    "DNC_VIOLATION": 1.25,
    "TIME_WINDOW": 1.0,
    "ABANDONMENT": 0.75,
    "RECORDING_CONSENT": 1.1,
}
SOURCE_POINTS = 10
VIOLATION_POINTS = 8
PROVISIONAL_ATTEMPT_POINTS = 2
ADJUDICATED_ATTEMPT_POINTS = 4
ATTEMPT_POINT_CAP = 5
LITIGATION_BONUS = 15

MEDIUM_THRESHOLD = 20
HIGH_THRESHOLD = 40
CRITICAL_THRESHOLD = 55

STATUTORY_BASE_CENTS = 50000
WILLFUL_MULTIPLIER = 3

PATTERN_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Scrubbing, revocation and attempt guards
# ---------------------------------------------------------------------------

PROPAGATION_BUSINESS_DAYS = 10
SCRUB_VALIDITY_DAYS = 31
LIST_REFRESH_MAX_DAYS = 31
CONTACT_COOLDOWN_MINUTES = 30
RND_VALIDITY_DAYS = 31

# ---------------------------------------------------------------------------
# Decimal comparison tolerance for the two-decimal money/percentage fields
# ---------------------------------------------------------------------------

DECIMAL_TOLERANCE = 0.01

# ---------------------------------------------------------------------------
# Reusable domain literals
# ---------------------------------------------------------------------------

PHONE_C1 = "+14155550101"
PHONE_C2 = "+14155550202"
PHONE_C3 = "+14155550303"
PHONE_NATIONAL_DNC = "+18005550000"

STATE_CA = "CA"
STATE_NV = "NV"
STATE_NY = "NY"

TZ_LOS_ANGELES = "America/Los_Angeles"
TZ_NEW_YORK = "America/New_York"
UTC_OFFSET_LOS_ANGELES = -420
UTC_OFFSET_NEW_YORK = -240

DEFAULT_ATTEMPT_BUDGET_TOTAL = 3
