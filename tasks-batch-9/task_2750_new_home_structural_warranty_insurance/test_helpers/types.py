"""Domain types for the New-Home Structural Warranty Insurance API.

Status enums, role enum and entity TypedDicts. Entities that the PRD declares
as immutable journal or reference rows expose ONLY ``id`` and ``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    UNDERWRITING_OFFICER = "UnderwritingOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    BUILDER_PRINCIPAL = "BuilderPrincipal"
    HOMEOWNER = "Homeowner"


# --------------------------------------------------------------------------
# Shared vocabularies
# --------------------------------------------------------------------------
class StateCode(str, Enum):
    TX = "TX"
    CO = "CO"
    AZ = "AZ"
    FL = "FL"
    NC = "NC"


class FinancialStrengthTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


# --------------------------------------------------------------------------
# Builder axis
# --------------------------------------------------------------------------
class BuilderUnderwritingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    REFERRED = "REFERRED"
    SUSPENDED = "SUSPENDED"
    DEFAULTED = "DEFAULTED"


class RiskClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class RiskBasis(str, Enum):
    INITIAL_UNDERWRITING = "INITIAL_UNDERWRITING"
    RENEWAL_REASSESSMENT = "RENEWAL_REASSESSMENT"


class MonitoringPosture(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class UnderwritingDecision(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    REFER = "REFER"


# --------------------------------------------------------------------------
# Policy axes
# --------------------------------------------------------------------------
class CoverageStatus(str, Enum):
    PENDING_ENROLLMENT = "PENDING_ENROLLMENT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class PremiumStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class CoverageType(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    SYSTEMS = "SYSTEMS"
    STRUCTURAL = "STRUCTURAL"


class TermKind(str, Enum):
    BASE = "BASE"
    ENDORSEMENT = "ENDORSEMENT"


class CoverageTermStatus(str, Enum):
    OPEN = "OPEN"
    LIMIT_EXHAUSTED = "LIMIT_EXHAUSTED"
    ELAPSED = "ELAPSED"


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    NEEDS_DOCUMENTATION = "NEEDS_DOCUMENTATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class TransferDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    BUILDER_OBLIGATION_NOTICE = "BUILDER_OBLIGATION_NOTICE"
    BUILDER_REPAIR_ACCEPTED = "BUILDER_REPAIR_ACCEPTED"
    CLOSED_REPAIRED = "CLOSED_REPAIRED"
    INSURER_ADJUDICATION = "INSURER_ADJUDICATION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLOSED_PAID = "CLOSED_PAID"
    MEDIATION = "MEDIATION"
    ARBITRATION = "ARBITRATION"
    CLOSED_SETTLED = "CLOSED_SETTLED"
    CLOSED_AWARDED = "CLOSED_AWARDED"
    CLOSED_DENIED_FINAL = "CLOSED_DENIED_FINAL"
    SUSPENDED_NO_LIMIT = "SUSPENDED_NO_LIMIT"


TERMINAL_CLAIM_STATUSES = [
    ClaimStatus.CLOSED_REPAIRED.value,
    ClaimStatus.CLOSED_PAID.value,
    ClaimStatus.CLOSED_SETTLED.value,
    ClaimStatus.CLOSED_AWARDED.value,
    ClaimStatus.CLOSED_DENIED_FINAL.value,
    ClaimStatus.SUSPENDED_NO_LIMIT.value,
]


class Obligor(str, Enum):
    BUILDER = "BUILDER"
    INSURER = "INSURER"


class DefectCategory(str, Enum):
    WORKMANSHIP_DEFECT = "WORKMANSHIP_DEFECT"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"
    STRUCTURAL_CRACKING = "STRUCTURAL_CRACKING"
    LOAD_BEARING_FAILURE = "LOAD_BEARING_FAILURE"
    WATER_INTRUSION = "WATER_INTRUSION"


class AffectedElement(str, Enum):
    FOOTING = "FOOTING"
    FOUNDATION_WALL = "FOUNDATION_WALL"
    BEAM = "BEAM"
    LOAD_BEARING_WALL = "LOAD_BEARING_WALL"
    ROOF_TRUSS = "ROOF_TRUSS"
    SLAB = "SLAB"
    NON_BEARING_PARTITION = "NON_BEARING_PARTITION"
    FINISH = "FINISH"


LOAD_BEARING_ELEMENTS = [
    AffectedElement.FOOTING.value,
    AffectedElement.FOUNDATION_WALL.value,
    AffectedElement.BEAM.value,
    AffectedElement.LOAD_BEARING_WALL.value,
    AffectedElement.ROOF_TRUSS.value,
    AffectedElement.SLAB.value,
]

NON_LOAD_BEARING_ELEMENTS = [
    AffectedElement.NON_BEARING_PARTITION.value,
    AffectedElement.FINISH.value,
]


class BuilderObligationResponse(str, Enum):
    ACCEPT_OBLIGATION = "ACCEPT_OBLIGATION"
    REFUSE_OBLIGATION = "REFUSE_OBLIGATION"


class AdjudicationOutcome(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# --------------------------------------------------------------------------
# Reserve journal
# --------------------------------------------------------------------------
class ReserveEntryType(str, Enum):
    INITIAL = "INITIAL"
    ADJUSTMENT = "ADJUSTMENT"
    PAYMENT = "PAYMENT"
    PAYMENT_REVERSAL = "PAYMENT_REVERSAL"
    RELEASE = "RELEASE"


# --------------------------------------------------------------------------
# Panel and escalation ladder
# --------------------------------------------------------------------------
class NeutralCredential(str, Enum):
    MEDIATOR = "MEDIATOR"
    ARBITRATOR = "ARBITRATOR"
    BOTH = "BOTH"


class NeutralStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EscalationStage(str, Enum):
    MEDIATION = "MEDIATION"
    ARBITRATION = "ARBITRATION"


class EscalationCaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SETTLED = "SETTLED"
    IMPASSE = "IMPASSE"
    AWARD_ISSUED = "AWARD_ISSUED"


class SessionOutcome(str, Enum):
    SETTLED = "SETTLED"
    IMPASSE = "IMPASSE"


# --------------------------------------------------------------------------
# Entity shapes
#
# Builder, Neutral, WarrantyPolicy, CoverageTerm, WarrantyTransfer, Claim and
# EscalationCase carry id + created_at + updated_at + version.
# UnderwritingReview, Homeowner, StructuralAssessment and ReserveEntry are
# immutable-once-written rows and carry ONLY id + created_at.
# --------------------------------------------------------------------------
class Builder(TypedDict):
    id: str
    company_name: str
    state_code: str
    years_in_business: int
    homes_closed_last_year: int
    claims_history_score: int
    financial_strength_tier: str
    underwriting_status: str
    risk_score: Optional[float]
    risk_class: Optional[str]
    risk_basis: Optional[str]
    obligation_period_years: int
    earned_premium_cents: int
    incurred_loss_cents: int
    loss_ratio: float
    monitoring_posture: str
    default_declared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnderwritingReview(TypedDict):
    id: str
    builder_id: str
    reviewer_user_id: str
    decision: str
    reviewer_notes: Optional[str]
    risk_score_snapshot: float
    risk_class_snapshot: str
    resulting_underwriting_status: str
    created_at: str


class Homeowner(TypedDict):
    id: str
    full_name: str
    email: str
    state_code: str
    created_at: str


class Neutral(TypedDict):
    id: str
    full_name: str
    credential: str
    state_code: str
    status: str
    booked_session_count: int
    created_at: str
    updated_at: str
    version: int


class WarrantyPolicy(TypedDict):
    id: str
    builder_id: str
    initial_owner_id: str
    current_owner_id: str
    street_address: str
    state_code: str
    purchase_price_cents: int
    closing_date: str
    coverage_start_date: str
    builder_obligation_end_date: str
    risk_class_at_enrollment: str
    premium_component_workmanship_cents: int
    premium_component_systems_cents: int
    premium_component_structural_cents: int
    state_surcharge_cents: int
    premium_cents: int
    coverage_status: str
    premium_status: str
    transfer_count: int
    enrollment_hold: bool
    pending_transfer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageTerm(TypedDict):
    id: str
    policy_id: str
    coverage_type: str
    term_kind: str
    start_date: str
    end_date: str
    limit_cents: int
    deductible_cents: int
    consumed_limit_cents: int
    remaining_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyTransfer(TypedDict):
    id: str
    policy_id: str
    new_owner_id: str
    requested_by_owner_id: str
    transfer_date: str
    documents_reference: Optional[str]
    transfer_fee_cents: int
    prior_transfer_id: Optional[str]
    decision_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    coverage_term_id: str
    filed_by_owner_id: str
    coverage_type: str
    defect_category: str
    damage_description: str
    claimed_amount_cents: int
    reported_date: str
    obligor: str
    designated_structural: bool
    substantiation_ratio: Optional[float]
    gross_adjusted_cents: int
    deductible_applied_cents: int
    betterment_cents: int
    net_payable_cents: int
    reserve_cents: int
    paid_cents: int
    released_cents: int
    incurred_authorized_cents: int
    adjudicated_by_user_id: Optional[str]
    denial_date: Optional[str]
    escalation_deadline_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StructuralAssessment(TypedDict):
    id: str
    claim_id: str
    affected_elements: List[str]
    deflection_ratio: float
    load_bearing_affected: bool
    designated_structural: bool
    assessed_by_user_id: str
    assessment_date: str
    created_at: str


class ReserveEntry(TypedDict):
    id: str
    claim_id: str
    entry_type: str
    amount_cents: int
    memo: Optional[str]
    recorded_by_user_id: str
    balance_after_reserve_cents: int
    balance_after_paid_cents: int
    reversed_entry_id: Optional[str]
    created_at: str


class EscalationCase(TypedDict):
    id: str
    claim_id: str
    neutral_id: str
    stage: str
    status: str
    binding: bool
    window_start: str
    window_end: str
    prior_case_id: Optional[str]
    settlement_amount_cents: Optional[int]
    award_amount_cents: Optional[int]
    outcome_recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
