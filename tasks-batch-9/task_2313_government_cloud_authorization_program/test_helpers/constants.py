"""Business constants for the Government Cloud Authorization Program API.

Every figure here is transcribed from the PRD so that test bodies never carry
unexplained magic numbers.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

#: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`".
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

# ---------------------------------------------------------------------------
# Impact levels and ranking (PRD 3.2)
# ---------------------------------------------------------------------------

IMPACT_LEVELS = ("LOW", "MODERATE", "HIGH")
IMPACT_RANK = {"LOW": 1, "MODERATE": 2, "HIGH": 3}

# ---------------------------------------------------------------------------
# Engagement pricing (PRD 3.5)
# ---------------------------------------------------------------------------

#: surcharge_rate tiers keyed on labor_cost_usd, never on the total.
SURCHARGE_TIER_LOW_CEILING = 250000.00
SURCHARGE_TIER_MID_CEILING = 600000.00
SURCHARGE_RATE_LOW = 0.06
SURCHARGE_RATE_MID = 0.045
SURCHARGE_RATE_HIGH = 0.03

#: Included hours per impact level, read from the offering's final_impact_level.
HOUR_ALLOWANCE = {"LOW": 400, "MODERATE": 900, "HIGH": 1600}

#: Dollars per hour charged on hours beyond the allowance.
HOUR_OVERAGE_RATE_USD = 120.00


def expected_surcharge_rate(labor_cost_usd: float) -> float:
    """Return the surcharge rate the PRD tier table selects for a labor cost."""
    if labor_cost_usd < SURCHARGE_TIER_LOW_CEILING:
        return SURCHARGE_RATE_LOW
    if labor_cost_usd < SURCHARGE_TIER_MID_CEILING:
        return SURCHARGE_RATE_MID
    return SURCHARGE_RATE_HIGH


# ---------------------------------------------------------------------------
# Remediation deadlines and residual risk (PRD 3.6)
# ---------------------------------------------------------------------------

#: Base day allowance per severity.
BASE_DAYS = {"HIGH": 30, "MODERATE": 90, "LOW": 180}

#: Severity weights used by both residual-risk variants.
SEVERITY_WEIGHT = {"HIGH": 10.0, "MODERATE": 4.0, "LOW": 1.0}

#: Disposition factors used by both residual-risk variants.
DISPOSITION_FACTOR = {
    "NONE": 1.0,
    "DEVIATION_REQUESTED": 1.0,
    "EXTENSION_GRANTED": 1.0,
    "RISK_ACCEPTED": 0.5,
    "FALSE_POSITIVE_ACCEPTED": 0.0,
}

#: Multiplier applied to an overdue finding's contribution.
OVERDUE_MULTIPLIER = 1.5

#: Residual risk floor and ceiling.
RISK_SCORE_FLOOR = 0.00
RISK_SCORE_CEILING = 100.00

#: poam_risk_tier thresholds.
RISK_TIER_LOW_FLOOR = 0.00
RISK_TIER_MODERATE_FLOOR = 10.00
RISK_TIER_ELEVATED_FLOOR = 30.00

#: requested_extension_days is an integer from 0 through 180 inclusive.
EXTENSION_DAYS_MIN = 0
EXTENSION_DAYS_MAX = 180

# ---------------------------------------------------------------------------
# Package submission gates and the authorization (PRD 3.7)
# ---------------------------------------------------------------------------

#: Coverage must be at least this percentage at submission.
CRM_COVERAGE_MINIMUM_PCT = 90.00

#: Submission-variant residual risk must be strictly below this figure.
RESIDUAL_RISK_SUBMISSION_CEILING = 50.00

#: An offering may hold at most this many package rows in total.
MAX_PACKAGES_PER_OFFERING = 3

#: A revision request raised at this round rejects the package outright.
REVISION_REJECTION_ROUND = 3

#: expires_at is this many days after authorized_at.
AUTHORIZATION_TERM_DAYS = 1095

#: reuse_seats_total opens at this figure.
REUSE_SEATS_TOTAL_DEFAULT = 5

LETTER_REFERENCE_PREFIX = "AUTH-LTR-"
LETTER_REFERENCE_BOARD_SUFFIX = "BOARD"


def expected_letter_reference(submission_round: int, agency_code: str = None) -> str:
    """`AUTH-LTR-<submission_round>-<agency_code|BOARD>` (PRD 3.7)."""
    tail = agency_code if agency_code else LETTER_REFERENCE_BOARD_SUFFIX
    return f"{LETTER_REFERENCE_PREFIX}{submission_round}-{tail}"


# ---------------------------------------------------------------------------
# Continuous monitoring (PRD 3.8)
# ---------------------------------------------------------------------------

#: scan_due_at is five days after window_end.
SCAN_DUE_OFFSET_DAYS = 5

#: Members of the scan_types array.
SCAN_TYPES = ("INFRASTRUCTURE", "WEB_APP", "DATABASE", "CONTAINER")

#: Three of the four are mandatory in every submission.
MANDATORY_SCAN_TYPES = ("INFRASTRUCTURE", "WEB_APP", "DATABASE")
OPTIONAL_SCAN_TYPE = "CONTAINER"

#: days_late thresholds driving a ScanSubmission's status.
LATE_ACCEPTED_MIN_DAYS = 1
LATE_ACCEPTED_MAX_DAYS = 3
REJECTED_MIN_DAYS = 4

#: consecutive_deficient_periods run lengths that drive propagation.
DEFICIENT_RUN_AT_RISK = 1
DEFICIENT_RUN_SUSPEND = 2
DEFICIENT_RUN_REVOKE = 3

# ---------------------------------------------------------------------------
# Significant changes and reuse (PRD 3.9)
# ---------------------------------------------------------------------------

#: Change windows must be separated by at least this many days on one side.
CHANGE_WINDOW_BUFFER_DAYS = 7

#: added_service_count at or above this figure forces reassessment.
REASSESSMENT_SERVICE_THRESHOLD = 3

#: An incremental-review acceptance tolerates at most this many findings.
INCREMENTAL_FINDINGS_TOLERANCE = 5

#: Agency sponsorship_capacity default.
SPONSORSHIP_CAPACITY_DEFAULT = 3

REVOKED_REASONS = ("AGENCY_REQUEST", "POSTURE_ESCALATION", "AUTHORIZATION_REVOKED")
