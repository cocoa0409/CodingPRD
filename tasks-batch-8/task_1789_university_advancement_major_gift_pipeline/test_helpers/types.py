"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    GIFT_OFFICER = "GiftOfficer"
    PROSPECT_RESEARCHER = "ProspectResearcher"
    ADVANCEMENT_DIRECTOR = "AdvancementDirector"
    VP_ADVANCEMENT = "VPAdvancement"
    DONOR_RELATIONS_OFFICER = "DonorRelationsOfficer"
    FINANCE_STEWARD = "FinanceSteward"


class FundraiserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ResearchStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    IN_SCREENING = "IN_SCREENING"
    RATED = "RATED"
    DISQUALIFIED = "DISQUALIFIED"


class MovesStage(str, Enum):
    QUALIFICATION = "QUALIFICATION"
    CULTIVATION = "CULTIVATION"
    SOLICITATION = "SOLICITATION"
    NEGOTIATION = "NEGOTIATION"
    STEWARDSHIP = "STEWARDSHIP"
    CLOSED_LOST = "CLOSED_LOST"


class CapacityBand(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class ProspectType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    ORGANIZATION = "ORGANIZATION"


class EvidenceTier(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    PUBLIC_RECORD = "PUBLIC_RECORD"
    VERIFIED_DOCUMENT = "VERIFIED_DOCUMENT"


class AssessmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReleasedReason(str, Enum):
    GRADUATED = "GRADUATED"
    REBALANCING = "REBALANCING"
    DISQUALIFIED = "DISQUALIFIED"


class ProposalType(str, Enum):
    OUTRIGHT = "OUTRIGHT"
    PLEDGE = "PLEDGE"
    PLANNED = "PLANNED"


class ApprovalTier(str, Enum):
    STANDARD = "STANDARD"
    MAJOR = "MAJOR"
    PRINCIPAL = "PRINCIPAL"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEGOTIATING = "NEGOTIATING"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class NamingStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RETIRED = "RETIRED"


class NamingCategory(str, Enum):
    BUILDING = "BUILDING"
    ENDOWED_CHAIR = "ENDOWED_CHAIR"
    SCHOLARSHIP = "SCHOLARSHIP"
    PROGRAM = "PROGRAM"


class RestrictionType(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    RESTRICTED_CURRENT_USE = "RESTRICTED_CURRENT_USE"
    ENDOWED = "ENDOWED"


class SignatureStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    EXECUTED = "EXECUTED"
    RESCINDED = "RESCINDED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    STEWARDSHIP_LAPSED = "STEWARDSHIP_LAPSED"


class FundStatus(str, Enum):
    PENDING_MINIMUM = "PENDING_MINIMUM"
    ACTIVE = "ACTIVE"
    SPENDING_FROZEN = "SPENDING_FROZEN"
    CLOSED = "CLOSED"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    WRITTEN_OFF = "WRITTEN_OFF"
    CANCELLED = "CANCELLED"


class PledgeFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REMINDED = "REMINDED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class WriteOffStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class WriteOffReason(str, Enum):
    UNCOLLECTIBLE = "UNCOLLECTIBLE"
    DONOR_HARDSHIP = "DONOR_HARDSHIP"
    DUPLICATE = "DUPLICATE"
    OTHER = "OTHER"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    WIRE = "WIRE"
    CARD = "CARD"
    STOCK = "STOCK"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    REPORTED = "REPORTED"


class CreditType(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DELIVERED = "DELIVERED"
    OVERDUE = "OVERDUE"


class SocietyLevel(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NEGOTIATE = "NEGOTIATE"
    RETURN = "RETURN"


# ---------------------------------------------------------------------------
# Entity payloads — every resource carries id / created_at / updated_at /
# version (the PRD declares no reduced-property resources).
# ---------------------------------------------------------------------------

class Fundraiser(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    max_prospect_count: int
    max_open_ask_cents: int
    current_prospect_count: int
    current_open_ask_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Prospect(TypedDict, total=False):
    id: str
    full_name: str
    prospect_type: str
    contact_email: str
    spouse_prospect_id: Optional[str]
    research_status: str
    moves_stage: str
    capacity_band: Optional[str]
    affinity_score: Optional[int]
    rated_assessment_id: Optional[str]
    rated_adjusted_capacity_cents: Optional[int]
    lifetime_given_cents: int
    outstanding_pledge_cents: int
    recognition_society_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResearchAssessment(TypedDict, total=False):
    id: str
    prospect_id: str
    assessed_capacity_cents: int
    engagement_score: int
    philanthropy_score: int
    recency_score: int
    evidence_tier: str
    adjusted_capacity_cents: Optional[int]
    capacity_band_result: Optional[str]
    affinity_score_result: Optional[int]
    created_by: str
    reviewed_by: Optional[str]
    review_rationale: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PortfolioAssignment(TypedDict, total=False):
    id: str
    fundraiser_id: str
    prospect_id: str
    status: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict, total=False):
    id: str
    prospect_id: str
    proposal_type: str
    ask_amount_cents: int
    designation_purpose: str
    approval_tier: Optional[str]
    effective_ask_cents: Optional[int]
    pinned_capacity_band: Optional[str]
    submitted_by: Optional[str]
    approvals_received: int
    approver_ids: List[str]
    decided_by: Optional[str]
    decision_rationale: Optional[str]
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NamingOpportunity(TypedDict, total=False):
    id: str
    name: str
    category: str
    price_floor_cents: int
    status: str
    reserved_by_agreement_id: Optional[str]
    reserved_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GiftAgreement(TypedDict, total=False):
    id: str
    proposal_id: str
    prospect_id: str
    restriction_type: str
    purpose_code: Optional[str]
    naming_opportunity_id: Optional[str]
    agreement_amount_cents: int
    reservation_expires_at: Optional[str]
    signature_status: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class RestrictedFund(TypedDict, total=False):
    id: str
    agreement_id: str
    purpose_code: Optional[str]
    is_endowed: bool
    balance_cents: int
    minimum_activation_cents: int
    trailing_market_values: List[dict]
    spendable_fy_cents: int
    allowance_remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict, total=False):
    id: str
    agreement_id: str
    prospect_id: str
    fund_id: Optional[str]
    campaign_id: Optional[str]
    total_amount_cents: int
    installment_count: int
    frequency: str
    first_due_date: str
    written_off_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PledgeInstallment(TypedDict, total=False):
    id: str
    pledge_id: str
    sequence_number: int
    due_date: str
    amount_cents: int
    paid_cents: int
    written_off_cents: int
    reminder_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PledgeWriteOff(TypedDict, total=False):
    id: str
    pledge_id: str
    amount_cents: int
    reason: str
    requested_by: str
    decided_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftPayment(TypedDict, total=False):
    id: str
    donor_prospect_id: str
    pledge_id: Optional[str]
    fund_id: Optional[str]
    campaign_id: Optional[str]
    amount_cents: int
    received_at: str
    payment_method: str
    corporate_matched: bool
    applied_allocations: List[dict]
    reversed: bool
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    name: str
    goal_cents: int
    counting_start: str
    counting_end: str
    face_value_counted_cents: int
    cash_counted_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CampaignCreditSplit(TypedDict, total=False):
    id: str
    campaign_id: Optional[str]
    gift_payment_id: str
    prospect_id: str
    credit_type: str
    split_pct: int
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class StewardshipReport(TypedDict, total=False):
    id: str
    fund_id: str
    period_start: str
    period_end: str
    due_date: str
    narrative: Optional[str]
    submitted_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecognitionSociety(TypedDict, total=False):
    id: str
    name: str
    level: str
    threshold_cash_cents: int
    benefits_text: Optional[str]
    created_at: str
    updated_at: str
    version: int
