"""Named constants taken verbatim from the PRD.

Nothing here is derived or guessed: every value below appears literally in the
PRD prose, so a test can reference the constant instead of repeating a magic
number.
"""

# ----------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ----------------------------------------------------------------------
# "the clock reads exactly 2026-08-01T00:00:00Z" before it has ever been set.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ----------------------------------------------------------------------
# Pagination (PRD 2.3)
# ----------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ----------------------------------------------------------------------
# Conformance testing (PRD 3.2)
# ----------------------------------------------------------------------
PASS_RATE_FLOOR = 0.9500
CONSECUTIVE_FAILURE_LIMIT = 3
CRITICAL_FAILURE_CATEGORIES = ("SECURITY", "PATIENT_ID_INTEGRITY")
REQUIRED_CERTIFICATION_PROFILES = ("ADT_PUBLISHER", "DOCUMENT_SOURCE", "QUERY_RESPONDER")

# ----------------------------------------------------------------------
# Threshold admissibility (PRD 3.3)
# ----------------------------------------------------------------------
WEIGHT_SUM_TARGET = 1.0000
WEIGHT_SUM_TOLERANCE = 0.0001

# ----------------------------------------------------------------------
# Identity matching (PRD 3.4)
# ----------------------------------------------------------------------
FUZZY_ELIGIBLE_FIELDS = ("family_name", "given_name", "postal_code", "phone_digits")
EXACT_MATCH_ONLY_FIELDS = ("birth_date", "ssn_last4")
BIRTH_DATE_VETO_CAP = 0.6000
STRONG_IDENTIFIER_FLOOR = 0.8000
COMPLETENESS_FIELDS = (
    "given_name",
    "family_name",
    "birth_date",
    "ssn_last4",
    "postal_code",
    "phone_digits",
)

# ----------------------------------------------------------------------
# Break-the-glass (PRD 3.8)
# ----------------------------------------------------------------------
JUSTIFICATION_MIN_LENGTH = 40
SESSION_LIFETIME_HOURS = 4
COOLDOWN_TAIL_HOURS = 1
COOLDOWN_TOTAL_HOURS = 5
SANCTION_POINTS_BY_CATEGORY = {
    "LIFE_THREATENING": 6,
    "UNCONSCIOUS_PATIENT": 4,
    "DISASTER": 3,
}
SENSITIVE_DISCLOSURE_SURCHARGE = 2
SANCTION_SUSPENSION_THRESHOLD = 12
SANCTION_DECAY_DAYS = 180
AUTOMATIC_SANCTION_THRESHOLD_REASON = "AUTOMATIC_SANCTION_THRESHOLD"

# ----------------------------------------------------------------------
# Feed monitoring and the scorecard (PRD 3.9)
# ----------------------------------------------------------------------
FEED_DEGRADED_REJECT_RATE = 0.0500
REJECT_RATE_BREACH_REASON = "REJECT_RATE_BREACH"
PARTICIPANT_SUSPENSION_CASCADE_REASON = "PARTICIPANT_SUSPENSION_CASCADE"
SUPERSEDED_BY_GENERATION_REASON = "SUPERSEDED_BY_GENERATION"
DUPLICATE_AFTER_CLUSTER_MERGE_REASON = "DUPLICATE_AFTER_CLUSTER_MERGE"
PARTICIPANT_TERMINATED_REASON = "PARTICIPANT_TERMINATED"

SCORECARD_WINDOW_DAYS = 90
SCORECARD_MAX_SAMPLES = 6
QUALIFYING_FEED_STATUSES = ("MONITORED", "DEGRADED")

COMPLETENESS_WEIGHT = 0.30
REJECTION_WEIGHT = 0.30
DUPLICATE_WEIGHT = 0.15
TIMELINESS_WEIGHT = 0.25

TIMELINESS_STEP_100_MAX_SECONDS = 300
TIMELINESS_STEP_85_MAX_SECONDS = 900
TIMELINESS_STEP_60_MAX_SECONDS = 3600

GRADE_A_FLOOR = 92
GRADE_B_FLOOR = 84
GRADE_C_FLOOR = 70

PENALTY_POINTS_BY_GRADE = {"A": 0, "B": 1, "C": 3, "D": 6}

# ----------------------------------------------------------------------
# Participation fee (PRD 3.9)
# ----------------------------------------------------------------------
TIER_1_UNIT_CAP = 24750
TIER_2_UNIT_SPAN = 75000
TIER_2_CUMULATIVE_CAP = 99750
TIER_1_RATE_CENTS = 1.75
TIER_2_RATE_CENTS = 1.25
TIER_3_RATE_CENTS = 0.65
BASE_PLATFORM_FEE_CENTS = 250000
QUALITY_MULTIPLIER_BY_GRADE = {
    "A": 0.95,
    "B": 1.00,
    "C": 1.08,
    "D": 1.20,
    "UNGRADED": 1.00,
}
PROVISIONAL_QUALITY_MULTIPLIER = 1.00

# Onboarding statuses from which an invoice may be issued (PRD 3.9 / 2.9).
INVOICEABLE_STATUSES = ("CONFORMANCE_TESTING", "CERTIFIED", "SUSPENDED", "TERMINATED")

# Invoice statuses that participate in the outstanding-balance sum (PRD 2.10).
BALANCE_BEARING_INVOICE_STATUSES = ("ISSUED", "DELINQUENT")

# Invoice statuses that block a re-issue over an overlapping window (PRD 3.9).
OVERLAP_BLOCKING_INVOICE_STATUSES = ("ISSUED", "PAID", "DELINQUENT", "WRITTEN_OFF")

# ----------------------------------------------------------------------
# Sensitive categories and purposes (PRD 3.6 / 3.7)
# ----------------------------------------------------------------------
ALL_SENSITIVE_CATEGORIES = ("BEHAVIORAL_HEALTH", "SUD", "HIV", "REPRODUCTIVE", "GENETIC")
NON_CLINICAL_PURPOSES = ("PAYMENT", "OPERATIONS")
