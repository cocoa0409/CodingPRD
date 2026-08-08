"""Domain thresholds and named constants, every value taken from PRD prose.

If a value here ever disagrees with the PRD, the citing test fails rather than
silently passing on a stale number.
"""

# ── The logical clock and the academic calendar (PRD §2.5) ──────────────────
# "a logical clock whose value before any client sets it is exactly
#  2026-05-01T00:00:00.000Z"
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00.000Z"

SUPPORTED_SCHOOL_YEARS = ["2025-2026", "2026-2027"]
SCHOOL_YEAR_2025_2026 = "2025-2026"
SCHOOL_YEAR_2026_2027 = "2026-2027"

# "2025-2026, which runs from 2025-08-01 through 2026-07-31, and 2026-2027,
#  which runs from 2026-08-01 through 2027-07-31"
SCHOOL_YEAR_START_DATE = {
    SCHOOL_YEAR_2025_2026: "2025-08-01",
    SCHOOL_YEAR_2026_2027: "2026-08-01",
}
SCHOOL_YEAR_END_DATE = {
    SCHOOL_YEAR_2025_2026: "2026-07-31",
    SCHOOL_YEAR_2026_2027: "2027-07-31",
}
# "the last second of the final day of that year expressed in UTC"
SCHOOL_YEAR_END_INSTANT = {
    SCHOOL_YEAR_2025_2026: "2026-07-31T23:59:59.000Z",
    SCHOOL_YEAR_2026_2027: "2027-07-31T23:59:59.000Z",
}

# ── Pagination (PRD §2.3) ───────────────────────────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ── Consent (PRD §3.4) ──────────────────────────────────────────────────────
# "the student's age in whole completed years at the current logical clock
#  date must be at least 14"
SELF_CONSENT_MIN_AGE_YEARS = 14
SELF_CONSENTABLE_CATEGORIES = ["BEHAVIORAL_HEALTH", "CONFIDENTIAL_SERVICES"]

# Which consent category each service line requires (PRD §3.4).
VISIT_TYPE_TO_CONSENT_CATEGORY = {
    "ACUTE": "GENERAL_TREATMENT",
    "ACUTE_CONFIDENTIAL": "CONFIDENTIAL_SERVICES",
    "BEHAVIORAL": "BEHAVIORAL_HEALTH",
    "DENTAL": "DENTAL",
    "SPORTS_PHYSICAL": "GENERAL_TREATMENT",
}

# Scope-of-practice mapping (PRD §3.1).
VISIT_TYPE_TO_DISCIPLINE = {
    "ACUTE": "MEDICAL",
    "BEHAVIORAL": "BEHAVIORAL",
    "DENTAL": "DENTAL",
    "SPORTS_PHYSICAL": "MEDICAL",
}

# ── Enrollment (PRD §3.3) ───────────────────────────────────────────────────
# "a row may be reinstated at most 2 times"
MAX_ENROLLMENT_REINSTATEMENTS = 2

# ── Encounter (PRD §3.5) ────────────────────────────────────────────────────
# "only once the current logical instant has reached scheduled_start_at plus
#  10 minutes"
NO_SHOW_GRACE_MINUTES = 10

# ── Telehealth (PRD §3.6) ───────────────────────────────────────────────────
# "that turnaround is 15 minutes"
TELEHEALTH_TURNAROUND_BUFFER_MINUTES = 15
# "must be at least 15 and at most 60, both bounds inclusive"
TELEHEALTH_MIN_DURATION_MINUTES = 15
TELEHEALTH_MAX_DURATION_MINUTES = 60
# "capped at 2 reschedules per row"
MAX_SESSION_RESCHEDULES = 2
# PRD §3.1: "when it is omitted the value defaults to 1, and any supplied
# value must be at least 1 and at most 4"
DEFAULT_TELEHEALTH_CONCURRENT_CAPACITY = 1
MIN_TELEHEALTH_CONCURRENT_CAPACITY = 1
MAX_TELEHEALTH_CONCURRENT_CAPACITY = 4

# ── Immunization (PRD §3.7) ─────────────────────────────────────────────────
HEPB_REQUIRED_DOSES = 3
MMR_REQUIRED_DOSES = 2
HEPB_DOSE1_MIN_AGE_DAYS = 0
MMR_DOSE1_MIN_AGE_DAYS = 365
HEPB_DOSE2_MIN_INTERVAL_DAYS = 28
HEPB_DOSE3_MIN_INTERVAL_DAYS = 56
MMR_DOSE2_MIN_INTERVAL_DAYS = 28
# "The earliest valid date is then the strict date pulled 4 days earlier"
IMMUNIZATION_GRACE_DAYS = 4
# "whose current logical clock date is at or before that activation date
#  advanced by 30 days"
PROVISIONAL_WINDOW_DAYS = 30

# ── Screening bands (PRD §3.8) ──────────────────────────────────────────────
VISION_REFER_DENOMINATOR_MIN = 40          # refers at 40 or more, inclusive
HEARING_REFER_DB_EXCLUSIVE = 25            # refers only above 25
DENTAL_REFER_CARIES_MIN = 1                # refers at 1 or more, inclusive
BMI_REFER_PERCENTILE_LOW_EXCLUSIVE = 5     # refers strictly below 5
BMI_REFER_PERCENTILE_HIGH_INCLUSIVE = 95   # refers at or above 95
BEHAVIORAL_REFER_SCORE_MIN = 10            # refers at 10 or more, inclusive

SCREENING_INSTRUMENT_TO_SPECIALTY = {
    "VISION": "OPHTHALMOLOGY",
    "HEARING": "AUDIOLOGY",
    "DENTAL": "DENTISTRY",
    "BMI": "NUTRITION",
    "BEHAVIORAL": "BEHAVIORAL_HEALTH",
}

# ── Referral (PRD §3.8) ─────────────────────────────────────────────────────
# "the cap is 3 attempts"
MAX_OUTREACH_ATTEMPTS = 3

# ── Sports-physical clearance (PRD §3.9) ────────────────────────────────────
# "The validity length is 365 days for CLEARED and 180 days for
#  CLEARED_WITH_RESTRICTIONS"
CLEARANCE_VALIDITY_DAYS_CLEARED = 365
CLEARANCE_VALIDITY_DAYS_RESTRICTED = 180
DEFERRAL_REEVALUATION_WINDOW_DAYS = 30
MAX_DEFERRAL_REEVALUATIONS = 2

# ── Notification (PRD §3.11) ────────────────────────────────────────────────
# "it is capped at 3 attempts"
MAX_NOTIFICATION_DELIVERY_ATTEMPTS = 3
# "at or before sent_at advanced by 14 days"
NOTIFICATION_ACK_WINDOW_DAYS = 14

# ── Sliding fee scale (PRD §3.2) ────────────────────────────────────────────
# "1,560,000 cents for a household of one, plus 550,000 cents for each
#  additional person"
FPL_BASE_ANNUAL_CENTS = 1_560_000
FPL_INCREMENT_PER_ADDITIONAL_PERSON_CENTS = 550_000

TIER_A_MAX_FPL_PERCENT = 100.00
TIER_B_MAX_FPL_PERCENT = 138.00
TIER_C_MAX_FPL_PERCENT = 175.00
TIER_D_MAX_FPL_PERCENT = 200.00

# "1.00 for TIER_A, 0.80 for TIER_B, 0.60 for TIER_C, 0.40 for TIER_D and
#  0.00 for TIER_E"
DISCOUNT_FRACTION = {
    "TIER_A": 1.00,
    "TIER_B": 0.80,
    "TIER_C": 0.60,
    "TIER_D": 0.40,
    "TIER_E": 0.00,
}

# ── Money (PRD §2.8, §3.10) ─────────────────────────────────────────────────
# "the encounter total is strictly below 500 cents"
NOMINAL_FEE_FLOOR_CENTS = 500
# "a flat 2,500 cents when it is PRIVATE_INSURANCE"
PRIVATE_COPAY_CENTS = 2_500
# "capped at 2 appeals"
MAX_CLAIM_APPEALS = 2

FEE_ACUTE_OFFICE_VISIT_CENTS = 12_000
FEE_BEHAVIORAL_THERAPY_CENTS = 15_000
FEE_DENTAL_PREVENTIVE_CENTS = 9_000
FEE_SPORTS_PHYSICAL_EXAM_CENTS = 5_000
FEE_IMMUNIZATION_ADMIN_CENTS = 3_000
FEE_TELEHEALTH_ENCOUNTER_CENTS = 11_000

FEE_SCHEDULE_CENTS = {
    "ACUTE_OFFICE_VISIT": FEE_ACUTE_OFFICE_VISIT_CENTS,
    "BEHAVIORAL_THERAPY": FEE_BEHAVIORAL_THERAPY_CENTS,
    "DENTAL_PREVENTIVE": FEE_DENTAL_PREVENTIVE_CENTS,
    "SPORTS_PHYSICAL_EXAM": FEE_SPORTS_PHYSICAL_EXAM_CENTS,
    "IMMUNIZATION_ADMIN": FEE_IMMUNIZATION_ADMIN_CENTS,
    "TELEHEALTH_ENCOUNTER": FEE_TELEHEALTH_ENCOUNTER_CENTS,
}

# "IMMUNIZATION_ADMIN is the one and only no-charge service category"
NO_CHARGE_SERVICE_CATEGORIES = ["IMMUNIZATION_ADMIN"]

# ── Reporting (PRD §2.8) ────────────────────────────────────────────────────
# "Referral closure rates in aggregate reports are carried to exactly 4
#  decimal places"
REPORT_RATE_PRECISION_DP = 4
MONEY_PRECISION_DP = 0

# ── Values reused across fixtures ───────────────────────────────────────────
TEST_DEFAULTS = {
    "CLOCK": "2026-05-04T09:00:00Z",
    "EARLY_CLOCK": "2026-05-04T08:00:00Z",
    "SPORTS_CLOCK": "2026-05-10T09:00:00Z",
    "SCHOOL_NAME": "Lincoln High",
    "SITE_CODE": "LHS",
    "SPONSOR_HOSPITAL": "Mercy Sponsor Hospital",
    "STUDENT_DOB": "2010-04-15",
    # income 3,000,000 at household size 4 -> 93.46% of the poverty level
    "TIER_A_INCOME_CENTS": 3_000_000,
    "TIER_A_HOUSEHOLD_SIZE": 4,
    # income 3,200,000 at household size 2 -> 151.66% of the poverty level
    "TIER_C_INCOME_CENTS": 3_200_000,
    "TIER_C_HOUSEHOLD_SIZE": 2,
}
