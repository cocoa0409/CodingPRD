"""Domain thresholds and pinned constants from PRD sections 2 and 3."""

# PRD section 2.6: the logical clock starts at this exact instant before any set.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# PRD section 3.2 / 3.5: drug currency extends 365 days past the latest
# qualifying NEGATIVE collected_date.
DRUG_CURRENCY_DAYS = 365

# PRD section 3.2: an earliest expiry within this many days of now yields
# posture RESTRICTED.
RESTRICTED_WINDOW_DAYS = 30

# PRD section 2.6 / 3.3: an EXPIRED credential lapses once its expiry lies
# more than 180 days before the clock.
CREDENTIAL_RENEWAL_GRACE_DAYS = 180

# PRD section 3.9: per-course cost cap applied before the channel percentage.
PER_COURSE_CAP_CENTS = 200_000

# PRD section 3.9: reimbursement channel percentages.
CHANNEL_PCT_DIRECT = 0.80
CHANNEL_PCT_UNION_HALL = 1.00

# PRD section 3.1: default annual training cap when omitted at registration.
DEFAULT_ANNUAL_TRAINING_CAP_CENTS = 500_000

# PRD section 3.8: cancellation fee percentage for TICKETED bookings.
CANCEL_FEE_PCT_TICKETED = 0.15

# PRD section 3.4: recognized upgrade targets and their requirements.
UPGRADE_REQUIREMENTS = {
    "CHIEF_MATE": {"days_required": 360, "lookback_months": 36,
                   "track": "DECK", "min_serving_grade": 4},
    "MASTER": {"days_required": 360, "lookback_months": 36,
               "track": "DECK", "min_serving_grade": 6},
    "SECOND_ENGINEER": {"days_required": 270, "lookback_months": 36,
                        "track": "ENGINE", "min_serving_grade": 4},
}

# Common fixture dates (all comfortably CLEAR of the 30-day restricted window
# against the default clock of 2026-08-01).
STD_MEDICAL_ISSUE = "2026-01-01T00:00:00Z"
STD_MEDICAL_EXPIRY = "2027-06-01T00:00:00Z"
STD_CREDENTIAL_ISSUE = "2026-01-01T00:00:00Z"
STD_CREDENTIAL_EXPIRY = "2030-01-01T00:00:00Z"
STD_DRUG_SCHEDULED = "2026-01-02T00:00:00Z"
STD_DRUG_COLLECTED = "2026-01-02T00:00:00Z"
STD_DRUG_CURRENT_UNTIL = "2027-01-02T00:00:00Z"

STD_PLAN_EFFECTIVE_FROM = "2026-08-01T00:00:00Z"
STD_PLAN_EFFECTIVE_TO = "2027-08-01T00:00:00Z"
STD_PLAN_TOUR_DAYS = 90
STD_PLAN_MAX_HANDOVER_DAYS = 3

STD_SIGN_ON = "2026-08-10T00:00:00Z"
STD_PLANNED_RELIEF = "2026-11-10T00:00:00Z"

STD_COURSE_START = "2026-09-01T00:00:00Z"
STD_COURSE_END = "2026-09-05T00:00:00Z"
