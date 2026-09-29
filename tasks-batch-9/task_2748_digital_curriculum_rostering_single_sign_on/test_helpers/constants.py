"""
Business constants for the Digital Curriculum Rostering & Single Sign-On API.

Every literal here is stated by the PRD (district password-policy defaults, the
logical-clock startup default, pagination defaults, the grade-band mapping,
the invoice discount ladder, the renewal weights and tier floors). Tests import
these rather than repeating magic numbers.
"""

# ── Logical clock ────────────────────────────────────────────────────────────
# "Before any call the clock reads exactly 2026-08-01T00:00:00Z (the mandatory
#  startup default) and NEVER falls back to real wall-clock time."
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ── Pagination (§2.3) ────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── District password-policy defaults (§3.1) ─────────────────────────────────
DEFAULT_MIN_PASSWORD_LENGTH = 8
DEFAULT_PASSWORD_REQUIRES_MIXED_CASE = True
DEFAULT_PASSWORD_MAX_AGE_DAYS = 180
DEFAULT_PASSWORD_LOCKOUT_THRESHOLD = 5
DEFAULT_TEMP_PASSWORD_TTL_HOURS = 72

MIN_PASSWORD_LENGTH_FLOOR = 6
MIN_PASSWORD_LENGTH_CEILING = 64
PASSWORD_MAX_AGE_DAYS_FLOOR = 30
PASSWORD_MAX_AGE_DAYS_CEILING = 365
PASSWORD_LOCKOUT_THRESHOLD_FLOOR = 3
PASSWORD_LOCKOUT_THRESHOLD_CEILING = 20
TEMP_PASSWORD_TTL_HOURS_FLOOR = 1
TEMP_PASSWORD_TTL_HOURS_CEILING = 336

# ── Term defaults and ranges ─────────────────────────────────────────────────
DEFAULT_ARCHIVE_RETENTION_DAYS = 90
ARCHIVE_RETENTION_DAYS_FLOOR = 0
ARCHIVE_RETENTION_DAYS_CEILING = 730
INSTRUCTIONAL_DAYS_FLOOR = 1
INSTRUCTIONAL_DAYS_CEILING = 250
SCHOOL_YEAR_FLOOR = 2000
SCHOOL_YEAR_CEILING = 2100

# ── Grade-band mapping for student subjects (§3.6) ───────────────────────────
# "grades 0 through 5 are ELEMENTARY, grades 6 through 8 are MIDDLE,
#  and grades 9 through 12 are HIGH"
ELEMENTARY_GRADE_LEVELS = list(range(0, 6))
MIDDLE_GRADE_LEVELS = list(range(6, 9))
HIGH_GRADE_LEVELS = list(range(9, 13))


def grade_band_for_grade_level(grade_level: int) -> str:
    """The district's standard grade_level -> grade band mapping (§3.6)."""
    if grade_level in ELEMENTARY_GRADE_LEVELS:
        return "ELEMENTARY"
    if grade_level in MIDDLE_GRADE_LEVELS:
        return "MIDDLE"
    return "HIGH"


# ── Invoice projection (§3.8) ────────────────────────────────────────────────
DISCOUNT_TIERS = [
    (5000000, 0.15),
    (2000000, 0.10),
    (500000, 0.05),
]
DISCOUNT_RATE_NONE = 0.00
PLATFORM_FEE_RATE = 0.03
PLATFORM_FEE_MINIMUM_CENTS = 25000
SHELFWARE_CREDIT_RATE = 0.25

# ── Renewal recommendation score (§3.8) ──────────────────────────────────────
UTILIZATION_WEIGHT = 0.50
ENGAGEMENT_WEIGHT = 0.30
COST_EFFICIENCY_WEIGHT = 0.20
ENGAGED_MINUTES_THRESHOLD = 120
ENGAGED_RECENCY_DAYS = 30
COST_EFFICIENCY_TARGET_CENTS = 1500
RENEW_SCORE_FLOOR = 70.0
RENEGOTIATE_SCORE_FLOOR = 40.0

# ── The standard academic term used across the suite ─────────────────────────
# Fall 2026: 10 Aug 2026 through 18 Dec 2026 inclusive is 131 total days,
# the add/drop cutoff is 15 Sep 2026, and 90 retention days after 18 Dec 2026
# is 18 Mar 2027 anchored at 00:00:00.000Z.
TERM_NAME = "Fall 2026"
TERM_SCHOOL_YEAR = 2026
TERM_START_DATE = "2026-08-10"
TERM_END_DATE = "2026-12-18"
TERM_ADD_DROP_CUTOFF_DATE = "2026-09-15"
TERM_INSTRUCTIONAL_DAYS = 85
TERM_ARCHIVE_RETENTION_DAYS = 90
TERM_TOTAL_DAYS = 131
TERM_ARCHIVED_ACCESS_EXPIRES_AT = "2027-03-18T00:00:00.000Z"

# ── Frequently used clock instants ───────────────────────────────────────────
CLOCK_BEFORE_TERM = "2026-08-01T00:00:00Z"
CLOCK_IN_WINDOW = "2026-08-20T00:00:00Z"
CLOCK_ON_CUTOFF = "2026-09-15T00:00:00Z"
CLOCK_AFTER_CUTOFF = "2026-09-16T00:00:00Z"
CLOCK_OCTOBER_FIRST = "2026-10-01T00:00:00Z"
CLOCK_AFTER_TERM_END = "2026-12-19T00:00:00Z"

# ── Money literals used by the pinned worked examples ────────────────────────
STANDARD_PRICE_PER_SEAT_CENTS = 1000
PRORATED_RATE_ON_OCTOBER_FIRST = 604  # ceil(1000 * 79 / 131)

# ── Passwords that satisfy / violate the default policy ──────────────────────
VALID_PASSWORD = "Rostering2026"          # 13 chars, mixed case
SHORT_PASSWORD = "Ab1"                    # below any min_password_length
LOWERCASE_ONLY_PASSWORD = "rostering2026"  # fails mixed case
