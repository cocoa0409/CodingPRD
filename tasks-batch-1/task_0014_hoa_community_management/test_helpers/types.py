"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4, top-level addressable entities carry (id, created_at, updated_at,
version). PaymentApplication and Vote are append-only event records: they carry
only id + created_at and explicitly omit updated_at and version.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Status enums ──────────────────────────────────────────────────────────

class AssessmentStatus(str, Enum):
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    WAIVED = "WAIVED"


class AssessmentKind(str, Enum):
    REGULAR = "REGULAR"
    SPECIAL = "SPECIAL"


class PaymentApplicationState(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    PAID = "PAID"
    ACTIVE = "ACTIVE"  # synthetic compliance-rollup label per PRD §3.5


class ViolationCategory(str, Enum):
    LANDSCAPING = "LANDSCAPING"
    APPEARANCE = "APPEARANCE"
    NOISE = "NOISE"
    PARKING = "PARKING"


class ACCRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ACCRequestScope(str, Enum):
    APPEARANCE = "APPEARANCE"
    LANDSCAPING = "LANDSCAPING"


class BoardElectionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED_QUORUM_MET = "CLOSED_QUORUM_MET"
    CLOSED_NO_QUORUM = "CLOSED_NO_QUORUM"
    CERTIFIED = "CERTIFIED"
    INVALIDATED = "INVALIDATED"


class VoteState(str, Enum):
    CAST = "CAST"
    RETRACTED = "RETRACTED"


class LienStatus(str, Enum):
    FILED = "FILED"
    SATISFIED = "SATISFIED"
    FORECLOSURE_INITIATED = "FORECLOSURE_INITIATED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSPENDED = "SUSPENDED"


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ReserveStudyMethod(str, Enum):
    COMPONENT = "COMPONENT"
    CASH_FLOW = "CASH_FLOW"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BOARD_PRESIDENT = "BoardPresident"
    BOARD_SECRETARY = "BoardSecretary"
    TREASURER = "Treasurer"
    ACC_MEMBER = "ACCMember"
    HOME_OWNER = "HomeOwner"


# ─── Entity TypedDicts ────────────────────────────────────────────────────

# Per PRD §2.4, these top-level entities carry the full quartet.

class Community(TypedDict):
    id: str
    name: str
    fiscal_year_start_month: int
    regular_assessment_cents: int
    late_fee_grace_days: int
    late_fee_flat_cents: int
    late_fee_pct_bps: int
    lien_threshold_cents: int
    election_quorum_pct: int
    reserve_inflation_bps: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict):
    id: str
    community_id: str
    email: str
    full_name: str
    is_eligible_voter: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    community_id: str
    owner_id: str
    unit_label: str
    account_balance_cents: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    property_id: str
    kind: str
    principal_cents: int
    late_fee_cents: int
    paid_cents: int
    outstanding_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    property_id: str
    category: str
    tier: int
    fine_cents: int
    status: str
    opened_at: str
    created_at: str
    updated_at: str
    version: int


class ACCRequest(TypedDict):
    id: str
    property_id: str
    scope: str
    description: str
    status: str
    revision_count: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoardElection(TypedDict):
    id: str
    community_id: str
    cycle_label: str
    opens_at: str
    closes_at: str
    status: str
    eligible_voter_count: int
    votes_cast: int
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    property_id: str
    principal_at_filing_cents: int
    status: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class ReserveStudy(TypedDict):
    id: str
    community_id: str
    fiscal_year: int
    method: str
    accumulated_funds_cents: int
    projected_obligation_cents: int
    percent_funded_bps: int
    created_at: str
    updated_at: str
    version: int


class ReserveComponent(TypedDict):
    id: str
    community_id: str
    label: str
    useful_life_years: int
    remaining_life_years: int
    replacement_cost_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only event records — id + created_at only per PRD §2.4.

class PaymentApplication(TypedDict):
    id: str
    assessment_id: str
    amount_cents: int
    state: str
    applied_at: str
    created_at: str


class Vote(TypedDict):
    id: str
    election_id: str
    owner_id: str
    candidate_name: str
    state: str
    cast_at: str
    created_at: str
