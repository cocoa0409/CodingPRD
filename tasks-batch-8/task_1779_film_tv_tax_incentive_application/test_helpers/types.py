"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common system-managed properties (id, created_at,
updated_at, version) per the PRD's common resource properties section.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FILM_OFFICE_ADMIN = "FilmOfficeAdmin"
    FILM_OFFICE_REVIEWER = "FilmOfficeReviewer"
    PRODUCER = "Producer"
    CPA_AUDITOR = "CPAAuditor"
    CREDIT_BUYER = "CreditBuyer"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    REVOKED = "REVOKED"


class ResidencyStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SpendEntryStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    SUPERSEDED = "SUPERSEDED"


class SpendCategory(str, Enum):
    ATL = "ATL"
    BTL = "BTL"


class ProductionType(str, Enum):
    FEATURE = "FEATURE"
    SERIES = "SERIES"
    DOCUMENTARY = "DOCUMENTARY"
    COMMERCIAL = "COMMERCIAL"


class AuditPackageStatus(str, Enum):
    ENGAGED = "ENGAGED"
    DRAFT_SUBMITTED = "DRAFT_SUBMITTED"
    FIELDWORK = "FIELDWORK"
    ATTESTED = "ATTESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_TRANSFERRED = "PARTIALLY_TRANSFERRED"
    FULLY_TRANSFERRED = "FULLY_TRANSFERRED"
    REDEEMED = "REDEEMED"
    CLAWED_BACK = "CLAWED_BACK"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    MANUAL = "MANUAL"
    INSUFFICIENT_REMAINING = "INSUFFICIENT_REMAINING"
    CERTIFICATE_CLAWED_BACK = "CERTIFICATE_CLAWED_BACK"


class ClawbackStatus(str, Enum):
    OPENED = "OPENED"
    NOTICE_SENT = "NOTICE_SENT"
    APPEALED = "APPEALED"
    SUSTAINED = "SUSTAINED"
    VACATED = "VACATED"
    SETTLED = "SETTLED"


class TriggerReason(str, Enum):
    SPEND_SHORTFALL = "SPEND_SHORTFALL"
    RESIDENCY_FAILURE = "RESIDENCY_FAILURE"
    MISSING_AUDIT = "MISSING_AUDIT"
    MISREPRESENTATION = "MISREPRESENTATION"


class PenaltyMode(str, Enum):
    SIMPLE = "SIMPLE"
    AGGRAVATED = "AGGRAVATED"


class JurisdictionProgram(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    program_name: str
    fiscal_year: str
    window_opens_at: str
    window_closes_at: str
    annual_cap_cents: int
    minimum_qualified_spend_cents: int
    base_rate_standard: float
    base_rate_elevated: float
    elevated_tier_threshold_cents: int
    atl_cap_pct: float
    resident_uplift_pct: float
    transfer_price_floor_pct: float
    vendor_verification_validity_days: int
    appeal_window_days: int
    daily_interest_rate: float
    credit_validity_days: int
    transfer_proposal_validity_days: int
    status: str
    allocated_credit_cents: int
    remaining_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductionCompany(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict, total=False):
    id: str
    production_company_id: str
    title: str
    production_type: str
    scheduled_start_date: str
    scheduled_wrap_date: str
    total_budget_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditBuyer(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class IncentiveApplication(TypedDict, total=False):
    id: str
    production_id: str
    jurisdiction_program_id: str
    estimated_qualified_spend_cents: int
    status: str
    submitted_at: Optional[str]
    reviewer_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    atl_qualified_cents: int
    btl_qualified_cents: int
    capped_total_qualified_cents: int
    provisional_credit_cents: int
    recomputed_credit_cents: int
    final_credit_cents: Optional[int]
    allocation_share_pct: float
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    production_id: str
    legal_name: str
    tax_id: str
    residency_jurisdiction: str
    residency_status: str
    verified_at: Optional[str]
    residency_reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpendEntry(TypedDict, total=False):
    id: str
    application_id: str
    vendor_id: str
    external_invoice_ref: str
    category: str
    is_resident_labor: bool
    spend_date: str
    amount_cents: int
    amends_entry_id: Optional[str]
    status: str
    effective_amount_cents: int
    disqualify_reason: Optional[str]
    reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditPackage(TypedDict, total=False):
    id: str
    application_id: str
    cpa_user_id: str
    status: str
    documentation_complete: bool
    attested_atl_cents: Optional[int]
    attested_btl_cents: Optional[int]
    exception_count: int
    attested_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditCertificate(TypedDict, total=False):
    id: str
    application_id: str
    certificate_number: str
    issued_amount_cents: int
    remaining_amount_cents: int
    redeemed_total_cents: int
    transferred_total_cents: int
    overissued_exposure_cents: int
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditTransfer(TypedDict, total=False):
    id: str
    certificate_id: str
    buyer_id: str
    seller_production_company_id: str
    amount_cents: int
    price_cents: int
    current_price_cents: int
    round_count: int
    status: str
    proposed_at: str
    expires_at: str
    settled_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClawbackCase(TypedDict, total=False):
    id: str
    application_id: str
    certificate_id: str
    trigger_reason: str
    penalty_mode: str
    shortfall_amount_cents: int
    status: str
    notice_sent_at: Optional[str]
    appeal_deadline_at: Optional[str]
    appealed_at: Optional[str]
    resolved_at: Optional[str]
    interest_cents: int
    assessed_total_cents: int
    recovered_from_certificate_cents: int
    cash_assessment_cents: int
    settled_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
