"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every entity in this domain carries the
full common field set (id + created_at + updated_at + version) per the PRD's
resource-identity rules; there are no append-only exceptions.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    DIVERSITY_ADMIN = "DiversityAdmin"
    DIVERSITY_ANALYST = "DiversityAnalyst"
    BUSINESS_UNIT_LEAD = "BusinessUnitLead"
    PRIME_CONTACT = "PrimeContact"
    AUDITOR = "Auditor"


class SupplierKind(str, Enum):
    DIVERSE = "DIVERSE"
    PRIME = "PRIME"
    BOTH = "BOTH"


class SupplierStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CertType(str, Enum):
    MBE = "MBE"
    WBE = "WBE"
    VET = "VET"
    SDVET = "SDVET"
    LGBTQBE = "LGBTQBE"
    DOBE = "DOBE"
    SBA8A = "SBA8A"
    SELF_CERT = "SELF_CERT"


class CertificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SpendRecordStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class Tier2ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class GoalType(str, Enum):
    PERCENT_OF_SPEND = "PERCENT_OF_SPEND"
    ABSOLUTE_AMOUNT = "ABSOLUTE_AMOUNT"


class GoalCategory(str, Enum):
    ALL = "ALL"
    MBE = "MBE"
    WBE = "WBE"
    VET = "VET"
    SDVET = "SDVET"
    LGBTQBE = "LGBTQBE"
    DOBE = "DOBE"
    SBA8A = "SBA8A"
    SELF_CERT = "SELF_CERT"


class ProgramGoalStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class AttributionBasis(str, Enum):
    ACCRUAL = "ACCRUAL"
    CASH = "CASH"


class ScorecardStatus(str, Enum):
    GENERATED = "GENERATED"
    PUBLISHED = "PUBLISHED"


class ScorecardRating(str, Enum):
    EXCEEDS = "EXCEEDS"
    MEETS = "MEETS"
    NEAR = "NEAR"
    BELOW = "BELOW"
    NO_GOAL = "NO_GOAL"


class SourcingEventStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class BidderInvitationStatus(str, Enum):
    INVITED = "INVITED"
    BID_SUBMITTED = "BID_SUBMITTED"
    DECLINED = "DECLINED"
    NO_RESPONSE = "NO_RESPONSE"
    WON = "WON"
    LOST = "LOST"
    WITHDRAWN = "WITHDRAWN"


class EngagementTrack(str, Enum):
    MENTORING = "MENTORING"
    CAPABILITY_BUILDING = "CAPABILITY_BUILDING"
    ACCESS_TO_CAPITAL = "ACCESS_TO_CAPITAL"


class DevelopmentEngagementStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class AuditOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class AuditCaseStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class BusinessUnit(TypedDict, total=False):
    id: str
    name: str
    code: str
    lead_user_id: str
    inclusion_min_diverse_bidders: int
    lifetime_imported_spend_cents: int
    lifetime_voided_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    kind: str
    contact_email: str
    status: str
    diverse_eligible: bool
    risk_score_standard: int
    risk_score_conservative: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    supplier_id: str
    cert_type: str
    certifying_body: str
    certificate_number: str
    valid_from: str
    valid_to: str
    status: str
    submitted_by_user_id: str
    verified_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpendRecord(TypedDict, total=False):
    id: str
    supplier_id: str
    business_unit_id: str
    amount_cents: int
    transaction_date: str
    payment_date: str
    po_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Tier2Line(TypedDict):
    diverse_supplier_id: str
    gross_subcontract_cents: int
    diverse_share_pct: float


class Tier2Report(TypedDict, total=False):
    id: str
    prime_supplier_id: str
    business_unit_id: str
    reporting_period: str
    lines: List[Tier2Line]
    total_subcontracted_cents: int
    total_diverse_tier2_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramGoal(TypedDict, total=False):
    id: str
    business_unit_id: str
    fiscal_year: int
    cert_category: str
    goal_type: str
    target_value: float
    include_tier2: bool
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Scorecard(TypedDict, total=False):
    id: str
    business_unit_id: str
    reporting_period: str
    attribution_basis: str
    total_spend_cents: int
    direct_diverse_spend_cents: int
    tier2_diverse_spend_cents: int
    spend_by_category: Dict[str, int]
    attainment_pct: Optional[float]
    rating: str
    goal_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SourcingEvent(TypedDict, total=False):
    id: str
    business_unit_id: str
    title: str
    estimated_value_cents: int
    required_diverse_bidders: int
    award_supplier_id: Optional[str]
    award_amount_cents: Optional[int]
    inclusion_waiver_reason: Optional[str]
    diverse_bid_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BidderInvitation(TypedDict, total=False):
    id: str
    sourcing_event_id: str
    supplier_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DevelopmentEngagement(TypedDict, total=False):
    id: str
    supplier_id: str
    track: str
    start_date: str
    end_date: str
    mentor_name: str
    capacity_score_before: int
    capacity_score_after: Optional[int]
    improvement: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    supplier_id: str
    certification_id: str
    reason: str
    auditor_user_id: str
    outcome: Optional[str]
    outcome_recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
