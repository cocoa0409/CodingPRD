"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CLIENT = "Client"
    ABSTRACTER = "Abstracter"
    EXAMINER = "Examiner"
    OPERATIONS_MANAGER = "OperationsManager"


class AbstractOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SEARCH_IN_PROGRESS = "SEARCH_IN_PROGRESS"
    SEARCH_COMPLETE = "SEARCH_COMPLETE"
    REPORT_DRAFTING = "REPORT_DRAFTING"
    REPORT_UNDER_REVIEW = "REPORT_UNDER_REVIEW"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SearchAssignmentStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class RecordDocumentStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    FLAGGED_FOR_CURATIVE = "FLAGGED_FOR_CURATIVE"
    VOID = "VOID"


class LegalDescriptionCheckStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    RESOLVED = "RESOLVED"


class AbstractReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CurativeRequirementStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"


class CountyRetrievalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FEE_POSTED = "FEE_POSTED"
    FEE_REVERSED = "FEE_REVERSED"
    INVOICED = "INVOICED"


class SlaTier(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class LiabilityTier(str, Enum):
    STANDARD = "STANDARD"
    EXTENDED = "EXTENDED"


class SearchType(str, Enum):
    CHAIN_OF_TITLE = "CHAIN_OF_TITLE"
    LIEN_JUDGMENT_TAX = "LIEN_JUDGMENT_TAX"


class InstrumentType(str, Enum):
    DEED = "DEED"
    MORTGAGE = "MORTGAGE"
    LIEN = "LIEN"
    JUDGMENT = "JUDGMENT"
    TAX_LIEN = "TAX_LIEN"
    EASEMENT = "EASEMENT"
    RESTRICTION = "RESTRICTION"


class CurativeSeverity(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class FeeMode(str, Enum):
    PER_DOCUMENT = "PER_DOCUMENT"
    PER_PAGE = "PER_PAGE"


class AbstractOrder(TypedDict, total=False):
    id: str
    client_ref: str
    property_address: str
    county: str
    state_code: str
    legal_description_text: str
    search_period_years: int
    effective_date: str
    sla_tier: str
    liability_tier: str
    scope_start_date: str
    received_at: str
    due_at: str
    delivered_at: Optional[str]
    is_overdue: bool
    status: str
    provisional_fee_cents: int
    accrued_fees_cents: int
    final_fee_cents: Optional[int]
    late_credit_cents: int
    billed_fee_cents: Optional[int]
    liability_cap_cents: int
    open_curative_count: int
    legal_hold: bool
    created_at: str
    updated_at: str
    version: int


class SearchAssignment(TypedDict, total=False):
    id: str
    order_id: str
    abstracter_ref: str
    search_type: str
    window_start: str
    window_end: str
    document_count: int
    verified_count: int
    revision_count: int
    return_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecordDocument(TypedDict, total=False):
    id: str
    order_id: str
    assignment_id: str
    instrument_type: str
    grantor_name: str
    grantee_name: str
    instrument_number: str
    recording_date: str
    prior_document_id: Optional[str]
    in_scope: bool
    chain_break_flag: bool
    exception_applies: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LegalDescriptionCheck(TypedDict, total=False):
    id: str
    order_id: str
    survey_reference: str
    checked_legal_description: str
    survey_exception_applied: bool
    resolved_description: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AbstractReport(TypedDict, total=False):
    id: str
    order_id: str
    title: str
    revision_number: int
    revision_reason: Optional[str]
    reviewer_examiner_ref: Optional[str]
    review_slot_start: Optional[str]
    review_slot_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CurativeRequirement(TypedDict, total=False):
    id: str
    order_id: str
    record_document_id: Optional[str]
    raised_by_examiner_ref: Optional[str]
    description: str
    severity: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CountyRetrieval(TypedDict, total=False):
    id: str
    order_id: str
    record_document_id: str
    county: str
    fee_mode: str
    page_count: Optional[int]
    fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
