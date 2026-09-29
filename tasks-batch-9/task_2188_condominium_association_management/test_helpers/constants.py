"""Domain constants transcribed from the PRD.

Nothing here is invented: every default matches the value the PRD says an
association is created with, and every enum tuple matches the PRD's declared
value set.  Money is always integer cents; ``_bp`` values are basis points
where 10000 means the whole.
"""

from __future__ import annotations

# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------
#: Before any client sets it, the logical clock reads exactly this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ----------------------------------------------------------------------
# Association defaults applied at creation time
# ----------------------------------------------------------------------
DEFAULT_FISCAL_YEAR_START_MONTH = 1
DEFAULT_MASTER_POLICY_DEDUCTIBLE_CENTS = 2_500_000
DEFAULT_ASSOCIATION_DEDUCTIBLE_CAP_CENTS = 1_000_000
DEFAULT_LATE_FEE_GRACE_DAYS = 10
DEFAULT_LATE_FEE_PERCENT_BP = 1000
DEFAULT_LATE_FEE_MIN_CENTS = 2_500
DEFAULT_LATE_FEE_CAP_CENTS = 10_000
DEFAULT_LIEN_THRESHOLD_CENTS = 180_000
DEFAULT_BUDGET_VETO_BP = 5000
DEFAULT_SPECIAL_ASSESSMENT_APPROVAL_BP = 6667
DEFAULT_BOARD_QUORUM_SEATS = 3
DEFAULT_HEARING_DOCKET_CAPACITY = 6
DEFAULT_ELEMENT_WINDOW_BUFFER_HOURS = 24
DEFAULT_RESERVE_ADEQUACY_THRESHOLD_BP = 7000
DEFAULT_RESERVE_CONTRIBUTION_MIN_BP = 1000
DEFAULT_FINE_TIER_1_CENTS = 5_000
DEFAULT_FINE_TIER_2_CENTS = 10_000
DEFAULT_FINE_TIER_3_DAILY_CENTS = 25_000
DEFAULT_FINE_CAP_CENTS = 250_000
DEFAULT_REPEAT_LOOKBACK_DAYS = 365
DEFAULT_CURE_PERIOD_DAYS = 14
DEFAULT_APPEAL_WINDOW_DAYS = 30
DEFAULT_BUDGET_NOTICE_DAYS = 30
DEFAULT_CERTIFICATE_VALIDITY_DAYS = 30
DEFAULT_RESALE_CERT_FEE_CENTS = 35_000

#: Undivided interest across a fully-populated association.
TOTAL_INTEREST_BP = 10_000

# ----------------------------------------------------------------------
# Roles
# ----------------------------------------------------------------------
ROLE_COMMUNITY_MANAGER = "CommunityManager"
ROLE_BOARD_DIRECTOR = "BoardDirector"
ROLE_BOARD_TREASURER = "BoardTreasurer"
ROLE_UNIT_OWNER = "UnitOwner"
ROLE_INSURANCE_ADJUSTER = "InsuranceAdjuster"
ROLE_ASSOCIATION_ATTORNEY = "AssociationAttorney"
ROLE_TITLE_AGENT = "TitleAgent"

ALL_ROLES = (
    ROLE_COMMUNITY_MANAGER,
    ROLE_BOARD_DIRECTOR,
    ROLE_BOARD_TREASURER,
    ROLE_UNIT_OWNER,
    ROLE_INSURANCE_ADJUSTER,
    ROLE_ASSOCIATION_ATTORNEY,
    ROLE_TITLE_AGENT,
)

#: Roles whose X-User-ID must resolve to a UnitOwner row.
ENTITY_BACKED_ROLES = (ROLE_BOARD_DIRECTOR, ROLE_BOARD_TREASURER, ROLE_UNIT_OWNER)

# ----------------------------------------------------------------------
# Enumerations
# ----------------------------------------------------------------------
BOARD_ROLES = ("NONE", "PRESIDENT", "VICE_PRESIDENT", "TREASURER", "SECRETARY", "DIRECTOR")

DELINQUENCY_STAGES = (
    "CURRENT",
    "REMINDER",
    "LATE_NOTICE",
    "COLLECTION_REFERRAL",
    "LIEN_FILED",
    "FORECLOSURE_REFERRAL",
)

LEDGER_BUCKETS = (
    "ASSESSMENT",
    "SPECIAL_ASSESSMENT",
    "LATE_FEE",
    "FINE",
    "INTEREST",
    "COLLECTION_COST",
)

#: Statutory application order used by the payment waterfall.
STATUTORY_WATERFALL_ORDER = (
    "INTEREST",
    "LATE_FEE",
    "COLLECTION_COST",
    "FINE",
    "ASSESSMENT",
    "SPECIAL_ASSESSMENT",
)

LEDGER_ENTRY_STATUSES = ("POSTED", "REVERSED", "SETTLED")

BUDGET_STATUSES = ("DRAFT", "PROPOSED", "NOTICED", "ADOPTED", "REJECTED", "SUPERSEDED")

SA_APPROVAL_STATUSES = ("DRAFT", "BALLOTING", "APPROVED", "FAILED", "RESCINDED")
SA_FUNDING_STATUSES = (
    "UNFUNDED",
    "PARTIALLY_COLLECTED",
    "FULLY_COLLECTED",
    "REFUNDING",
    "REFUNDED",
)

MEETING_STATUSES = ("SCHEDULED", "NOTICED", "IN_SESSION", "ADJOURNED", "CANCELLED")

ELEMENT_STATUSES = ("SERVICEABLE", "IMPAIRED", "OUT_OF_SERVICE", "DECOMMISSIONED")

CONTRACT_STATUSES = (
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "ACTIVE",
    "SUSPENDED",
    "TERMINATED",
    "EXPIRED",
)

WORK_ORDER_STATUSES = (
    "SCHEDULED",
    "IN_PROGRESS",
    "ON_HOLD",
    "COMPLETED",
    "INVOICED",
    "CANCELLED",
)

CLAIM_ADJUSTMENT_STATUSES = (
    "REPORTED",
    "UNDER_REVIEW",
    "ADJUSTED_ASSOCIATION",
    "ADJUSTED_OWNER",
    "ADJUSTED_SPLIT",
    "DENIED",
    "SETTLED",
    "APPEALED",
)
CLAIM_LITIGATION_STATUSES = ("NONE", "TENDERED", "IN_LITIGATION", "RESOLVED")

CASE_STATUSES = (
    "OPEN",
    "NOTICE_SENT",
    "HEARING_SCHEDULED",
    "FINE_ASSESSED",
    "APPEALED",
    "FINE_UPHELD",
    "FINE_VACATED",
    "DISMISSED",
    "CURED",
)

CERTIFICATE_STATUSES = ("REQUESTED", "ISSUED", "VOIDED", "EXPIRED")

PAYOFF_BASES = ("LEDGER_BALANCE", "ESTIMATED_PAYOFF")

RESERVE_BASES = ("STRAIGHT_LINE", "COMPONENT")

RESERVE_POSTURES = ("ADEQUATE", "DEFICIENT")

# ----------------------------------------------------------------------
# Derived ceilings expressed as helpers so tests stay literal-free where
# the PRD states a formula rather than a number.
# ----------------------------------------------------------------------
#: Invoice overrun ceiling: floor(estimated_cost_cents * 11 / 10), inclusive.
def invoice_overrun_ceiling_cents(estimated_cost_cents: int) -> int:
    return estimated_cost_cents * 11 // 10


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Integer division rounding halves away from zero, as the PRD prescribes."""
    if denominator == 0:
        raise ZeroDivisionError("denominator must be non-zero")
    sign = -1 if (numerator < 0) != (denominator < 0) else 1
    n, d = abs(numerator), abs(denominator)
    return sign * ((2 * n + d) // (2 * d))
