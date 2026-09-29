"""Business constants for the payroll tax amendment and wage statement correction API.

Every literal here is taken from the PRD: role names, enum vocabularies, the
logical-clock default, pagination bounds, and the pinned worked examples the PRD
states verbatim.
"""

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PAYROLL_ANALYST = "PayrollAnalyst"
ROLE_TAX_PREPARER = "TaxPreparer"
ROLE_TAX_OFFICER = "TaxOfficer"
ROLE_CONTROLS_AUDITOR = "ControlsAuditor"
ROLE_EMPLOYER_REP = "EmployerRep"
ROLE_EMPLOYEE_SELF_SERVICE = "EmployeeSelfService"

OPAQUE_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PAYROLL_ANALYST,
    ROLE_TAX_PREPARER,
    ROLE_TAX_OFFICER,
    ROLE_CONTROLS_AUDITOR,
)
ENTITY_BACKED_ROLES = (ROLE_EMPLOYER_REP, ROLE_EMPLOYEE_SELF_SERVICE)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# "Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z"
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Period ordinals
# ---------------------------------------------------------------------------
OPEN_ENDED_PERIOD_ORDINAL = 999999


def period_ordinal(tax_year: int, quarter: int) -> int:
    """Period ordinal: the tax year multiplied by four plus the quarter minus one."""
    return tax_year * 4 + (quarter - 1)


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
DEPOSIT_SCHEDULES = ("MONTHLY", "SEMIWEEKLY")
AGENCY_LEVELS = ("FEDERAL", "STATE", "LOCAL")
INTEREST_METHODS = ("STATUTORY_DAILY", "DEPOSIT_WEIGHTED")
REGISTRATION_STATUSES = ("PENDING", "RETRO_PENDING", "ACTIVE", "RETRO_ACTIVE", "CLOSED")
POSTING_STATUSES = ("POSTED",)
CLEARING_STATUSES = ("CLEARED", "RETURNED")
FILED_RETURN_STATUSES = ("FILED", "AMENDED")

CASE_STATUSES = ("OPEN", "REMEDIATION_PENDING", "CLOSED")
DETECTION_STATUSES = ("NOT_RUN", "NO_VARIANCE", "VARIANCE_FOUND")
FILING_STATUSES = (
    "FILING_NOT_REQUIRED",
    "FILING_PENDING",
    "FILING_IN_PROGRESS",
    "FILING_COMPLETE",
)
STATEMENT_DIMENSION_STATUSES = (
    "STMT_NOT_REQUIRED",
    "STMT_PENDING",
    "STMT_ISSUED",
    "STMT_REISSUE_PENDING",
    "STMT_COMPLETE",
)

DISCREPANCY_CATEGORIES = (
    "TAXABLE_WAGE",
    "WITHHOLDING",
    "JURISDICTION_ASSIGNMENT",
    "DEPOSIT_SHORTFALL",
)
DISCREPANCY_STATUSES = ("OPEN", "CATEGORIZED", "RESOLVED", "DISMISSED", "SUPERSEDED")
ROOT_CAUSE_CODES = (
    "RATE_TABLE_STALE",
    "JURISDICTION_MAPPING_ERROR",
    "THIRD_PARTY_FEED_ERROR",
    "MANUAL_ENTRY_ERROR",
    "DEPOSIT_SCHEDULING_ERROR",
)

AMENDED_RETURN_STATUSES = (
    "DRAFT",
    "PREPARED",
    "SIGNED",
    "SUBMITTED",
    "ACCEPTED",
    "AGENCY_REJECTED",
    "VOID",
)
STATEMENT_STATUSES = ("DRAFT", "ISSUED", "ACKNOWLEDGED", "RETURNED_UNDELIVERABLE", "VOIDED")
DELIVERY_CHANNELS = ("MAIL", "PORTAL")

REPAYMENT_STATUSES = ("PROPOSED", "AGREED", "COLLECTED", "WRITTEN_OFF", "CANCELLED")
RECOVERY_BASES = ("SAME_YEAR_NET", "PRIOR_YEAR_GROSS")
SETTLED_REPAYMENT_STATUSES = ("COLLECTED", "WRITTEN_OFF", "CANCELLED")

NOTICE_RESPONSE_STATUSES = (
    "RECEIVED",
    "RESPONSE_DRAFTED",
    "RESPONDED",
    "INFO_REQUESTED",
    "CLOSED",
)
NOTICE_ABATEMENT_STATUSES = ("NONE", "REQUESTED", "GRANTED", "PARTIALLY_GRANTED", "DENIED")
ABATEMENT_GROUNDS = ("FIRST_TIME", "REASONABLE_CAUSE", "STATUTORY_EXCEPTION", "AGENCY_ERROR")
ABATEMENT_OUTCOMES = ("ABATED_FULL", "ABATED_PARTIAL", "UPHELD")

CONTROL_GAP_CLASSES = ("PROCESS_CONTROL", "SYSTEM_CONTROL", "THIRD_PARTY_FAILURE")
REMEDIATION_STATUSES = (
    "OPEN",
    "SUBMITTED_FOR_VERIFICATION",
    "VERIFIED",
    "VERIFICATION_FAILED",
)
OPEN_REMEDIATION_STATUSES = ("OPEN", "SUBMITTED_FOR_VERIFICATION", "VERIFICATION_FAILED")

# ---------------------------------------------------------------------------
# Common-field shape. Register lines and deposit records are immutable evidence
# rows and carry only id and created_at.
# ---------------------------------------------------------------------------
FULL_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
EVIDENCE_COMMON_FIELDS = ("id", "created_at")

# ---------------------------------------------------------------------------
# Waiver percentages in basis points
# ---------------------------------------------------------------------------
BPS_FULL = 10000
BPS_HALF = 5000
REASONABLE_CAUSE_BASE_BPS = 6000
THIRD_PARTY_FAILURE_BONUS_BPS = 2000
FIRST_TIME_GROSS_CEILING_CENTS = 5000000
DE_MINIMIS_CEILING_CENTS = 2500

# ---------------------------------------------------------------------------
# Penalty ladder
# ---------------------------------------------------------------------------
FTD_TIER_1_BPS = 200   # 5 days late or fewer
FTD_TIER_2_BPS = 500   # 6 through 15 days late
FTD_TIER_3_BPS = 1000  # 16 days late or more
FTF_MONTHLY_BPS = 500
FTF_CEILING_BPS = 2500
PENALTY_FLOOR_CENTS = 5000
VOLUNTARY_REDUCTION_BPS = 2500

# ---------------------------------------------------------------------------
# Auto-created remediation from the acceptance cascade
# ---------------------------------------------------------------------------
CASCADE_REMEDIATION_TARGET_OFFSET_DAYS = 30
CASCADE_REMEDIATION_GAP_CLASS = "PROCESS_CONTROL"

# ---------------------------------------------------------------------------
# Pinned worked examples the PRD states verbatim
# ---------------------------------------------------------------------------
# "three lines of 100001 cents each at a workday share of 5000 basis points
#  round to 50001 cents per line and sum to 150003 cents, whereas rounding the
#  aggregate would give 150002 cents"
APPORTION_PER_LINE_CENTS = 50001
APPORTION_PER_LINE_SUM_CENTS = 150003
APPORTION_AGGREGATE_ROUNDING_CENTS = 150002

# "DEPOSIT_WEIGHTED yields 34833 cents while STATUTORY_DAILY on identical
#  inputs yields 30000 cents"
DEPOSIT_WEIGHTED_EXAMPLE_INTEREST_CENTS = 34833
STATUTORY_DAILY_EXAMPLE_INTEREST_CENTS = 30000

# "SAME_YEAR_NET yields an amount due of 309400 cents and an agency-recoverable
#  amount of 90600 cents, while PRIOR_YEAR_GROSS on identical inputs yields
#  400000 cents and 30600 cents"
REPAYMENT_EXAMPLE_GROSS_CENTS = 400000
REPAYMENT_EXAMPLE_INCOME_TAX_CENTS = 60000
REPAYMENT_EXAMPLE_FICA_CENTS = 30600
SAME_YEAR_NET_DUE_CENTS = 309400
SAME_YEAR_NET_RECOVERABLE_CENTS = 90600
PRIOR_YEAR_GROSS_DUE_CENTS = 400000
PRIOR_YEAR_GROSS_RECOVERABLE_CENTS = 30600

# ---------------------------------------------------------------------------
# Canonical federal 2025 Q1 scenario used by many tests
# ---------------------------------------------------------------------------
CANON_CLOCK = "2026-04-30T00:00:00Z"
CANON_TAX_YEAR = 2025
CANON_QUARTER = 1
CANON_FILED_DUE_DATE = "2025-04-30T00:00:00.000Z"
CANON_ACCRUAL_THROUGH = "2026-04-30"
CANON_AUTHORIZATION_LIMIT_CENTS = 5000000
CANON_REGISTER_WAGE_TOTAL_CENTS = 5000000
CANON_REGISTER_WITHHELD_TOTAL_CENTS = 750000
CANON_REPORTED_WAGE_CENTS = 4750000
CANON_REPORTED_WITHHELD_CENTS = 500000
CANON_WAGE_VARIANCE_CENTS = 250000
CANON_WITHHOLDING_VARIANCE_CENTS = 250000
CANON_DEPOSIT_SHORTFALL_CENTS = 250000
CANON_DAYS_LATE = 365
CANON_INTEREST_CENTS = 20000
CANON_PENALTY_CENTS = 65625
CANON_TOTAL_EXPOSURE_CENTS = 335625

# Non-existent identifiers used by the not-found reads
UNKNOWN_ID_TEMPLATE = "00000000-0000-0000-0000-0000000{:05d}"
UNKNOWN_CASE_ID = "00000000-0000-0000-0000-000000009999"
