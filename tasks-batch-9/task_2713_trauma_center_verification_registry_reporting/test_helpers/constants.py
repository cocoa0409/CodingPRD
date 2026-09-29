"""Numeric thresholds, weights and deadlines the contract fixes by name."""

# ─── The logical clock ────────────────────────────────────

# On startup the logical clock reads exactly this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ─── Pagination ───────────────────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ─── Decimal comparison ───────────────────────────────────

# Every stored decimal is carried to exactly two decimal places.
DECIMAL_TOLERANCE = 0.01

# ─── Activation tier bounds ───────────────────────────────

MIN_RESPONSE_LIMIT_MINUTES = 1
MAX_RESPONSE_LIMIT_MINUTES = 240
MIN_ISS_THRESHOLD = 0
MAX_ISS_THRESHOLD = 75

# ─── Data dictionary error weights, derived from severity ─

ERROR_WEIGHT_CRITICAL = 4
ERROR_WEIGHT_MAJOR = 2
ERROR_WEIGHT_MINOR = 1

ERROR_WEIGHT_BY_SEVERITY = {
    "CRITICAL": ERROR_WEIGHT_CRITICAL,
    "MAJOR": ERROR_WEIGHT_MAJOR,
    "MINOR": ERROR_WEIGHT_MINOR,
}

# ─── Compliance band multipliers ──────────────────────────

BAND_HIGH_FLOOR = 95.00          # score >= 95.00 -> multiplier 1.0
BAND_MID_FLOOR = 90.00           # score >= 90.00 -> multiplier 1.5
BAND_MULTIPLIER_HIGH = 1.0
BAND_MULTIPLIER_MID = 1.5
BAND_MULTIPLIER_LOW = 2.0

# ─── Registry case inclusion classification ───────────────

TRANSFER_OUT_LOS_HOURS_CEILING = 24.00
TRANSFER_OUT_ISS_CEILING = 9
BELOW_INJURY_THRESHOLD_ISS = 4

# ─── Abstraction timeliness ───────────────────────────────

ABSTRACTION_WINDOW_DAYS = 60

# ─── Triage rate thresholds ───────────────────────────────

UNDER_TRIAGE_ALERT_RATE_PCT = 5.00
OVER_TRIAGE_CONDITIONAL_RATE_PCT = 35.00

# The verification-audit numerator predicates.
AUDIT_UNDER_TRIAGE_ISS_FLOOR = 16   # the Cribari severity line
AUDIT_OVER_TRIAGE_ISS_CEILING = 9

# ─── Readiness posture ladder ─────────────────────────────

POSTURE_SUSPEND_ESCALATED_CRITICAL_COUNT = 2
POSTURE_AT_RISK_OPEN_CRITICAL_COUNT = 1
POSTURE_CONDITIONAL_OPEN_PI_COUNT = 3

# ─── PI loop deadlines ────────────────────────────────────

LOOP_CLOSURE_DAYS = 60            # manual, under-triage and delayed-surgeon loops
REOPENED_LOOP_CLOSURE_DAYS = 30   # a reopened loop gets a shorter leash
DEFICIENCY_ESCALATION_LOOP_DAYS = 30
ESCALATION_REMEDIATION_DAYS = 30

# ─── Readiness score assembly ─────────────────────────────

READINESS_BASE_SCORE = 100.00
SUBMIT_MIN_READINESS = 70.00
PREP_BLOCK_THRESHOLD = 70.00

DEFICIENCY_PENALTY_TYPE_I = 15
DEFICIENCY_PENALTY_TYPE_II = 6
DEFICIENCY_PENALTY_TYPE_III = 2
DEFICIENCY_PENALTY_CAP = 60

NATIONAL_REQUIRED_OUTREACH_HOURS = 12.00
STATE_REQUIRED_OUTREACH_HOURS = 8.00
OUTREACH_GAP_MULTIPLIER = 1.5
OUTREACH_PENALTY_CAP = 20.00

NATIONAL_PI_POINTS_PER_OPEN_EVENT = 4
NATIONAL_PI_POINTS_PER_OVERDUE_LOOP = 8
NATIONAL_PI_PENALTY_CAP = 20
STATE_PI_POINTS_PER_OPEN_EVENT = 2
STATE_PI_PENALTY_CAP = 10

REGISTRY_PENALTY_MULTIPLIER = 0.25
PERFECT_COMPLIANCE_SCORE = 100.00

# ─── Outreach credit weighting ────────────────────────────

OUTREACH_WEIGHT_INJURY_PREVENTION = 1.5
OUTREACH_WEIGHT_PROFESSIONAL_EDUCATION = 1.0
OUTREACH_WEIGHT_COMMUNITY_OUTREACH = 0.5

OUTREACH_WEIGHT_BY_KIND = {
    "INJURY_PREVENTION": OUTREACH_WEIGHT_INJURY_PREVENTION,
    "PROFESSIONAL_EDUCATION": OUTREACH_WEIGHT_PROFESSIONAL_EDUCATION,
    "COMMUNITY_OUTREACH": OUTREACH_WEIGHT_COMMUNITY_OUTREACH,
}

QUARTER_HOUR = 0.25

# ─── Referral agreements ──────────────────────────────────

MIN_GUARANTEED_ACCEPTANCE_MINUTES = 1
MAX_GUARANTEED_ACCEPTANCE_MINUTES = 720

# ─── Surveyor bookings ────────────────────────────────────

DEFAULT_TRAVEL_BUFFER_HOURS = 24
