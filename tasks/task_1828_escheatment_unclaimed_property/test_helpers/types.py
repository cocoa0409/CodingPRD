"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    HOLDER_ADMIN = "HolderAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STATE_AUDITOR = "StateAuditor"
    TREASURY_OPS = "TreasuryOps"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    CLAIMS_APPROVER = "ClaimsApprover"
    CLAIMANT = "Claimant"


class PropertyType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    BROKERAGE_SHARES = "BROKERAGE_SHARES"
    UNCASHED_CHECK = "UNCASHED_CHECK"
    INSURANCE_PROCEEDS = "INSURANCE_PROCEEDS"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    DUE_DILIGENCE = "DUE_DILIGENCE"
    REPORTABLE = "REPORTABLE"
    REPORTED = "REPORTED"
    REMITTED = "REMITTED"
    ESCHEATED = "ESCHEATED"
    REUNITED = "REUNITED"


class ContactType(str, Enum):
    WITHDRAWAL = "WITHDRAWAL"
    DEPOSIT = "DEPOSIT"
    LOGIN_VERIFIED = "LOGIN_VERIFIED"
    WRITTEN_CORRESPONDENCE = "WRITTEN_CORRESPONDENCE"
    PHONE_VERIFIED = "PHONE_VERIFIED"
    IN_PERSON = "IN_PERSON"


class LetterStatus(str, Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"
    UNDELIVERABLE = "UNDELIVERABLE"
    VOIDED = "VOIDED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LineItemStatus(str, Enum):
    INCLUDED = "INCLUDED"
    FINAL = "FINAL"
    REMOVED = "REMOVED"


class LineType(str, Enum):
    CASH = "CASH"
    SECURITIES = "SECURITIES"


class SecuritiesDetailStatus(str, Enum):
    REGISTERED = "REGISTERED"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    LIQUIDATED = "LIQUIDATED"


class LiquidationOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RemittanceStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"


class PenaltyAssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    DISPUTED = "DISPUTED"


class AuditCaseStatus(str, Enum):
    OPENED = "OPENED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class ArtifactType(str, Enum):
    LETTER_COPY = "LETTER_COPY"
    REPORT_FILE = "REPORT_FILE"
    CLAIM_EVIDENCE = "CLAIM_EVIDENCE"
    REMITTANCE_RECEIPT = "REMITTANCE_RECEIPT"


class RelatedEntityType(str, Enum):
    DUE_DILIGENCE_LETTER = "DueDiligenceLetter"
    HOLDER_REPORT = "HolderReport"
    OWNER_CLAIM = "OwnerClaim"
    REMITTANCE = "Remittance"


class DocumentRecordStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PURGED = "PURGED"


# All entities carry the standard system-managed fields of PRD §2.4
# (id, created_at, updated_at, version).

class Owner(TypedDict, total=False):
    id: str
    full_name: str
    last_known_address: str
    state_code: str
    deceased_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DormancyRule(TypedDict, total=False):
    id: str
    state_code: str
    property_type: str
    dormancy_years: int
    effective_from: str
    effective_to: Optional[str]
    dd_threshold_cents: int
    dd_window_min_days: int
    dd_window_max_days: int
    annual_interest_rate_bp: int
    daily_penalty_cents: int
    gross_daily_penalty_cents: int
    gross_negligence_day_threshold: int
    penalty_cap_pct: int
    report_cutoff_month_day: str
    report_due_month_day: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    owner_id: str
    property_type: str
    state_code: str
    original_value_cents: int
    last_contact_date: str
    status: str
    dormancy_date: Optional[str]
    escheated_date: Optional[str]
    reunited_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContactEvent(TypedDict, total=False):
    id: str
    property_id: str
    contact_type: str
    contact_date: str
    evidence_ref: str
    qualifies_for_reactivation: bool
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DueDiligenceLetter(TypedDict, total=False):
    id: str
    property_id: str
    sent_date: str
    response_deadline: str
    applicable_due_date: str
    status: str
    response_contact_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HolderReport(TypedDict, total=False):
    id: str
    state_code: str
    report_year: int
    status: str
    supersedes_report_id: Optional[str]
    cutoff_date: str
    due_date: str
    submitted_date: Optional[str]
    submitted_by_user_id: Optional[str]
    accepted_date: Optional[str]
    rejection_reason: Optional[str]
    total_provisional_cents: int
    total_final_cents: int
    confirmed_remittance_cents: int
    line_count: int
    created_at: str
    updated_at: str
    version: int


class ReportLineItem(TypedDict, total=False):
    id: str
    report_id: str
    property_id: str
    line_type: str
    provisional_value_cents: int
    final_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SecuritiesDetail(TypedDict, total=False):
    id: str
    property_id: str
    cusip: str
    shares_quantity: int
    last_close_price_cents: int
    accrued_dividends_cents: int
    pending_execution_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LiquidationOrder(TypedDict, total=False):
    id: str
    property_id: str
    liquidation_fee_cents: int
    execution_price_cents_per_share: Optional[int]
    executed_date: Optional[str]
    settled_date: Optional[str]
    gross_proceeds_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict, total=False):
    id: str
    report_id: str
    amount_cents: int
    status: str
    failure_reason: Optional[str]
    confirmed_date: Optional[str]
    variance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OwnerClaim(TypedDict, total=False):
    id: str
    property_id: str
    claimant_owner_id: str
    claim_type: str
    evidence_ref: Optional[str]
    status: str
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    approved_base_cents: Optional[int]
    approved_interest_cents: Optional[int]
    processing_fee_cents: Optional[int]
    approved_payout_cents: Optional[int]
    paid_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict, total=False):
    id: str
    report_id: str
    assessed_date: str
    days_late: int
    penalty_cents: int
    interest_cents: int
    total_cents: int
    status: str
    waiver_reason: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    state_code: str
    lookback_start_year: int
    lookback_end_year: int
    status: str
    estimated_exposure_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DocumentRecord(TypedDict, total=False):
    id: str
    artifact_type: str
    related_entity_type: str
    related_entity_id: str
    retention_until: str
    purged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
