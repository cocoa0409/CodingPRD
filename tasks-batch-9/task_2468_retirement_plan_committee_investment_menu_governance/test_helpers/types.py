"""Entity status vocabularies and lightweight typed shapes for the
retirement-plan committee / investment-menu governance API.

Every name here is taken from the PRD: the six role names of §2.1, the state
vocabularies of §3.1–§3.9, and the enumerated field domains of the entity
descriptions.  Nothing in this module talks to the network.
"""

from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class Role:
    """The six role names accepted in the ``X-User-Role`` header."""

    PLAN_SPONSOR_ADMIN = "PlanSponsorAdmin"
    COMMITTEE_CHAIR = "CommitteeChair"
    COMMITTEE_MEMBER = "CommitteeMember"
    INVESTMENT_CONSULTANT = "InvestmentConsultant"
    RECORDKEEPER = "Recordkeeper"
    PLAN_AUDITOR = "PlanAuditor"

    ALL = (
        PLAN_SPONSOR_ADMIN,
        COMMITTEE_CHAIR,
        COMMITTEE_MEMBER,
        INVESTMENT_CONSULTANT,
        RECORDKEEPER,
        PLAN_AUDITOR,
    )

    #: The two roles whose ``X-User-ID`` must resolve to a committee member row.
    ENTITY_BACKED = (COMMITTEE_CHAIR, COMMITTEE_MEMBER)


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------


class CharterStatus:
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class MenuPosture:
    """The plan-wide derived gate of PRD §2.9."""

    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class FeeDisclosureStatus:
    COMPLIANT = "COMPLIANT"
    RESTATEMENT_REQUIRED = "RESTATEMENT_REQUIRED"


# --------------------------------------------------------------------------
# Committee
# --------------------------------------------------------------------------


class SeatStatus:
    VACANT = "VACANT"
    FILLED = "FILLED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class SeatClass:
    CHAIR = "CHAIR"
    SPONSOR_FIDUCIARY = "SPONSOR_FIDUCIARY"
    FINANCE = "FINANCE"
    HR = "HR"
    PARTICIPANT_REP = "PARTICIPANT_REP"
    INDEPENDENT = "INDEPENDENT"


class SeatStatusAction:
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    RETIRE = "RETIRE"


class PlanType:
    FOUR_01K = "401K"
    FOUR_03B = "403B"
    FOUR_57B = "457B"


class MemberStatus:
    APPOINTED = "APPOINTED"
    TRAINING_ASSIGNED = "TRAINING_ASSIGNED"
    ACCEPTANCE_PENDING = "ACCEPTANCE_PENDING"
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"
    TERM_EXPIRED = "TERM_EXPIRED"

    #: The statuses that make an appointment "live" for term-overlap and
    #: seat-occupancy purposes (PRD §3.2).
    LIVE = (APPOINTED, TRAINING_ASSIGNED, ACCEPTANCE_PENDING, ACTIVE)
    TERMINAL = (RESIGNED, REMOVED, TERM_EXPIRED)


class TrainingStatus:
    """``FiduciaryTrainingRecord.status``."""

    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class FiduciaryTrainingStatus:
    """``CommitteeMember.fiduciary_training_status``."""

    PENDING = "PENDING"
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class TrainingModule:
    FIDUCIARY_DUTIES = "FIDUCIARY_DUTIES"
    IPS_MECHANICS = "IPS_MECHANICS"
    FEE_BENCHMARKING = "FEE_BENCHMARKING"
    PROHIBITED_TRANSACTIONS = "PROHIBITED_TRANSACTIONS"

    #: The modules whose currency decides ``fiduciary_training_status``.
    REQUIRED = (FIDUCIARY_DUTIES, IPS_MECHANICS)
    #: Informational modules that never gate activation.
    INFORMATIONAL = (FEE_BENCHMARKING, PROHIBITED_TRANSACTIONS)


class ProviderRole:
    """``affiliated_provider_role`` on a member and ``provider_role`` on an
    engagement.  ``NONE`` is only meaningful on the member side."""

    NONE = "NONE"
    RECORDKEEPER = "RECORDKEEPER"
    ADVISOR = "ADVISOR"
    AUDITOR = "AUDITOR"
    CUSTODIAN = "CUSTODIAN"

    #: The four roles an engagement may be registered under.
    ENGAGEMENT_ROLES = (RECORDKEEPER, ADVISOR, AUDITOR, CUSTODIAN)


class EndTermReason:
    RESIGNATION = "RESIGNATION"
    REMOVAL_FOR_CAUSE = "REMOVAL_FOR_CAUSE"
    TERM_EXPIRY = "TERM_EXPIRY"


# --------------------------------------------------------------------------
# Policy statement, slots and funds
# --------------------------------------------------------------------------


class IpsStatus:
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ScoringVariant:
    TRAILING_PERIOD = "TRAILING_PERIOD"
    ROLLING_SINCE_WATCH = "ROLLING_SINCE_WATCH"


class SlotStatus:
    EMPTY = "EMPTY"
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    PENDING_REPLACEMENT = "PENDING_REPLACEMENT"
    RETIRED = "RETIRED"

    #: Statuses that consume an occupied menu position (PRD §2.10).
    OCCUPYING = (ACTIVE, AT_RISK, PENDING_REPLACEMENT)


class SlotDesignation:
    CORE = "CORE"
    SPECIALTY = "SPECIALTY"
    QDIA = "QDIA"


class AssetClass:
    US_LARGE_CAP = "US_LARGE_CAP"
    US_SMALL_CAP = "US_SMALL_CAP"
    INTL_DEVELOPED = "INTL_DEVELOPED"
    EMERGING_MKTS = "EMERGING_MKTS"
    CORE_BOND = "CORE_BOND"
    TIPS = "TIPS"
    STABLE_VALUE = "STABLE_VALUE"
    REAL_ASSETS = "REAL_ASSETS"
    TARGET_DATE = "TARGET_DATE"
    SELF_DIRECTED = "SELF_DIRECTED"


class ShareClass:
    R1 = "R1"
    R3 = "R3"
    R6 = "R6"
    INSTITUTIONAL = "INSTITUTIONAL"
    ADMIN = "ADMIN"
    INVESTOR = "INVESTOR"


class FundMenuStatus:
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    PENDING_REMOVAL = "PENDING_REMOVAL"
    REMOVED = "REMOVED"


class WatchStatus:
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    REMEDIATION = "REMEDIATION"
    TERMINATION_PENDING = "TERMINATION_PENDING"


class CreditAccrualStatus:
    NOT_ACCRUING = "NOT_ACCRUING"
    ACCRUING = "ACCRUING"
    CLOSED_OUT = "CLOSED_OUT"


class GlidepathType:
    TO_RETIREMENT = "TO_RETIREMENT"
    THROUGH_RETIREMENT = "THROUGH_RETIREMENT"


class Construction:
    OFF_THE_SHELF = "OFF_THE_SHELF"
    CUSTOM = "CUSTOM"


# --------------------------------------------------------------------------
# Reviews and scorecards
# --------------------------------------------------------------------------


class ReviewStatus:
    DRAFT = "DRAFT"
    SCORING = "SCORING"
    PENDING_MINUTES = "PENDING_MINUTES"
    FINALIZED = "FINALIZED"
    REOPENED = "REOPENED"
    VOID = "VOID"


class ScorecardStatus:
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class WatchRecommendation:
    NONE = "NONE"
    WATCH = "WATCH"
    REMEDIATION = "REMEDIATION"
    TERMINATE = "TERMINATE"


# --------------------------------------------------------------------------
# Meetings, motions, votes
# --------------------------------------------------------------------------


class MeetingStatus:
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED = "ADJOURNED"
    MINUTES_APPROVED = "MINUTES_APPROVED"
    VOID = "VOID"


class MotionStatus:
    OPEN = "OPEN"
    CARRIED = "CARRIED"
    FAILED = "FAILED"
    TABLED = "TABLED"
    WITHDRAWN = "WITHDRAWN"


class MotionSubjectType:
    IPS_ADOPTION = "IPS_ADOPTION"
    FUND_REPLACEMENT = "FUND_REPLACEMENT"
    TARGET_DATE_SELECTION = "TARGET_DATE_SELECTION"
    FEE_LEVELIZATION = "FEE_LEVELIZATION"
    RFP_AWARD = "RFP_AWARD"
    WATCH_LIST_ACTION = "WATCH_LIST_ACTION"


class TallyBasis:
    VOTES_CAST = "VOTES_CAST"
    ELIGIBLE_VOTERS = "ELIGIBLE_VOTERS"


class Vote:
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"
    RECUSE = "RECUSE"


# --------------------------------------------------------------------------
# Replacement proposals
# --------------------------------------------------------------------------


class ProposalStatus:
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    BLOCKED = "BLOCKED"
    APPROVED = "APPROVED"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    EXECUTED = "EXECUTED"
    UNWOUND = "UNWOUND"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"

    #: Statuses counted by ``Plan.draft_proposal_count``.
    OPEN_PIPELINE = (DRAFT, UNDER_REVIEW, REVISION_REQUESTED, BLOCKED)
    #: Statuses that hold a reserved menu position (PRD §2.10).
    RESERVING = (APPROVED, NOTICE_ISSUED)


class MappingStrategy:
    DIRECT_MAP = "DIRECT_MAP"
    MAP_TO_QDIA = "MAP_TO_QDIA"
    REENROLLMENT = "REENROLLMENT"


# --------------------------------------------------------------------------
# Fee levelization and provider oversight
# --------------------------------------------------------------------------


class LevelizationStatus:
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    RECALC_REQUIRED = "RECALC_REQUIRED"
    REVERSED = "REVERSED"
    VOID = "VOID"


class LevelizationMethod:
    PER_CAPITA = "PER_CAPITA"
    PRO_RATA = "PRO_RATA"


class EngagementStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    UNDER_RFP = "UNDER_RFP"
    TERMINATED = "TERMINATED"
    SUPERSEDED = "SUPERSEDED"

    #: Statuses that block an overlapping term on the same plan and role.
    LIVE = (PENDING, ACTIVE, UNDER_RFP)


class FeeCreditTier:
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


# --------------------------------------------------------------------------
# Convenience aliases
# --------------------------------------------------------------------------

Headers = Dict[str, str]
JsonDict = Dict[str, Any]
JsonList = List[JsonDict]

#: Fields every entity in this system carries (PRD §2.4).
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

__all__ = [
    "Role",
    "CharterStatus",
    "MenuPosture",
    "FeeDisclosureStatus",
    "SeatStatus",
    "SeatClass",
    "SeatStatusAction",
    "PlanType",
    "MemberStatus",
    "TrainingStatus",
    "FiduciaryTrainingStatus",
    "TrainingModule",
    "ProviderRole",
    "EndTermReason",
    "IpsStatus",
    "ScoringVariant",
    "SlotStatus",
    "SlotDesignation",
    "AssetClass",
    "ShareClass",
    "FundMenuStatus",
    "WatchStatus",
    "CreditAccrualStatus",
    "GlidepathType",
    "Construction",
    "ReviewStatus",
    "ScorecardStatus",
    "WatchRecommendation",
    "MeetingStatus",
    "MotionStatus",
    "MotionSubjectType",
    "TallyBasis",
    "Vote",
    "ProposalStatus",
    "MappingStrategy",
    "LevelizationStatus",
    "LevelizationMethod",
    "EngagementStatus",
    "FeeCreditTier",
    "Headers",
    "JsonDict",
    "JsonList",
    "Optional",
    "COMMON_FIELDS",
]
