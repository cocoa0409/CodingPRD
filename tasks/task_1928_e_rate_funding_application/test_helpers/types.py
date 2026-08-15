"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    APPLICANT_COORDINATOR = "ApplicantCoordinator"
    APPLICANT_CERTIFIER = "ApplicantCertifier"
    VENDOR_REPRESENTATIVE = "VendorRepresentative"
    PIA_REVIEWER = "PIAReviewer"
    COMMITMENT_OFFICER = "CommitmentOfficer"
    INVOICE_PROCESSOR = "InvoiceProcessor"
    APPEAL_OFFICER = "AppealOfficer"
    AUDITOR = "Auditor"


class Category(str, Enum):
    CATEGORY_ONE = "CATEGORY_ONE"
    CATEGORY_TWO = "CATEGORY_TWO"


class ServiceType(str, Enum):
    INTERNET_ACCESS = "INTERNET_ACCESS"
    DATA_TRANSMISSION = "DATA_TRANSMISSION"
    VOICE_SERVICE = "VOICE_SERVICE"
    INTERNAL_CONNECTIONS = "INTERNAL_CONNECTIONS"
    BASIC_MAINTENANCE = "BASIC_MAINTENANCE"


class EntityType(str, Enum):
    SCHOOL = "SCHOOL"
    LIBRARY = "LIBRARY"


class UrbanRural(str, Enum):
    URBAN = "URBAN"
    RURAL = "RURAL"


class UserFunction(str, Enum):
    COORDINATOR = "COORDINATOR"
    CERTIFIER = "CERTIFIER"


class PostingStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    TERMINATED = "TERMINATED"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    PIA_REVIEW = "PIA_REVIEW"
    INFORMATION_REQUESTED = "INFORMATION_REQUESTED"
    COMMITTED = "COMMITTED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class LineDenialReason(str, Enum):
    REQUEST_DENIED = "REQUEST_DENIED"
    INSUFFICIENT_BUDGET = "INSUFFICIENT_BUDGET"
    CONTRACT_TERMINATED = "CONTRACT_TERMINATED"


class InvoiceMethod(str, Enum):
    BEAR = "BEAR"
    SPI = "SPI"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class SubstitutionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class DocumentStatus(str, Enum):
    RETAINED = "RETAINED"
    HELD = "HELD"
    PURGED = "PURGED"


class SubjectType(str, Enum):
    CONTRACT = "CONTRACT"
    FUNDING_REQUEST = "FUNDING_REQUEST"
    INVOICE_SUBMISSION = "INVOICE_SUBMISSION"
    SERVICE_SUBSTITUTION = "SERVICE_SUBSTITUTION"
    APPEAL = "APPEAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts — primary resources carry id + created_at + updated_at +
# version (PRD §2.5). The NSLP snapshot is the deliberate append-only
# exception: only id + created_at (no updated_at, no version).
# ---------------------------------------------------------------------------

class FundingCycle(TypedDict):
    id: str
    label: str
    window_open_date: str
    window_close_date: str
    service_delivery_deadline: str
    created_at: str
    updated_at: str
    version: int


class EligibleService(TypedDict):
    id: str
    funding_cycle_id: str
    service_description: str
    category: str
    service_type: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    name: str
    entity_type: str
    urban_rural: str
    student_count: Optional[int]
    square_feet: Optional[int]
    audit_hold_active: bool
    created_at: str
    updated_at: str
    version: int


class NSLPSnapshot(TypedDict):
    # Append-only fact: carries only id + created_at (PRD §2.5).
    id: str
    applicant_id: str
    funding_cycle_id: str
    total_students: int
    free_lunch_eligible_students: int
    cep_participating: bool
    cep_identified_student_pct: Optional[float]
    effective_share_pct: float
    created_at: str


class ApplicantUser(TypedDict):
    id: str
    applicant_id: str
    display_name: str
    function: str
    created_at: str
    updated_at: str
    version: int


class ServiceProvider(TypedDict):
    id: str
    name: str
    spin: str
    created_at: str
    updated_at: str
    version: int


class ProcurementPosting(TypedDict):
    id: str
    applicant_id: str
    funding_cycle_id: str
    category: str
    description: str
    price_weight_pct: int
    other_factor_weights: list
    status: str
    posted_at: Optional[str]
    window_close_at: Optional[str]
    selected_bid_id: Optional[str]
    selected_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    posting_id: str
    service_provider_id: str
    eligible_price_cents: int
    ineligible_price_cents: int
    factor_scores: list
    total_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    applicant_id: str
    service_provider_id: str
    posting_id: str
    winning_bid_id: str
    category: str
    total_eligible_cents: int
    service_start_date: str
    service_end_date: str
    status: str
    certified_date: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingRequest(TypedDict):
    id: str
    applicant_id: str
    funding_cycle_id: str
    status: str
    nslp_share_pct: Optional[float]
    discount_rate_c1_pct: Optional[int]
    discount_rate_c2_pct: Optional[int]
    committed_total_share_cents: int
    services_started: bool
    service_start_date: Optional[str]
    pia_reviewer_user_ids: list
    decision_date: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingRequestLine(TypedDict):
    id: str
    funding_request_id: str
    contract_id: str
    eligible_service_id: str
    category: str
    requested_pre_discount_cents: int
    committed_pre_discount_cents: int
    committed_share_cents: int
    reimbursed_cents: int
    remaining_reimbursable_cents: int
    invoice_deadline_date: Optional[str]
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceSubmission(TypedDict):
    id: str
    frn_line_id: str
    method: str
    submitted_by_provider_id: Optional[str]
    gross_invoiced_cents: int
    applicant_paid_cents: Optional[int]
    approved_reimbursement_cents: Optional[int]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceSubstitution(TypedDict):
    id: str
    frn_line_id: str
    from_eligible_service_id: str
    to_eligible_service_id: str
    supersedes_substitution_id: Optional[str]
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    funding_request_id: str
    grounds: str
    filed_date: str
    status: str
    outcome_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetainedDocument(TypedDict):
    id: str
    subject_type: str
    subject_id: str
    funding_cycle_id: str
    document_kind: str
    retained_until_date: str
    status: str
    hold_start_date: Optional[str]
    hold_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int
