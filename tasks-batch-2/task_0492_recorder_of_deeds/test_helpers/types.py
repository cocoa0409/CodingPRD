"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full set of common fields
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    SUBMITTER = "Submitter"
    EXAMINER = "Examiner"
    RECORDER = "Recorder"
    CLERK = "Clerk"


# --- Status / enum vocabularies ---
class SubmitterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SubmitterType(str, Enum):
    TITLE_COMPANY = "TITLE_COMPANY"
    ATTORNEY = "ATTORNEY"
    SELF = "SELF"
    GOVERNMENT = "GOVERNMENT"


class DocType(str, Enum):
    DEED = "DEED"
    MORTGAGE = "MORTGAGE"
    LIEN = "LIEN"
    UCC = "UCC"
    PLAT = "PLAT"
    OTHER = "OTHER"


class PackageStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_EXAMINATION = "IN_EXAMINATION"
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PartyRole(str, Enum):
    GRANTOR = "GRANTOR"
    GRANTEE = "GRANTEE"


class PartyEntryStatus(str, Enum):
    PENDING = "PENDING"
    INDEXED = "INDEXED"
    VOIDED = "VOIDED"


class FeeAssessmentStatus(str, Enum):
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    ESCROW = "ESCROW"
    CARD = "CARD"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"


class RecordedDocumentStatus(str, Enum):
    RECORDED = "RECORDED"
    CORRECTED_VOID = "CORRECTED_VOID"


class RejectionReasonCode(str, Enum):
    MARGIN = "MARGIN"
    NOTARY = "NOTARY"
    LEGAL_DESCRIPTION = "LEGAL_DESCRIPTION"
    INDEX_INCOMPLETE = "INDEX_INCOMPLETE"
    FEE_DISCREPANCY = "FEE_DISCREPANCY"


class PlatStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"


class LienType(str, Enum):
    UCC1 = "UCC1"
    TAX_LIEN = "TAX_LIEN"
    JUDGMENT_LIEN = "JUDGMENT_LIEN"
    MECHANICS_LIEN = "MECHANICS_LIEN"


class LienStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class RequestType(str, Enum):
    CERTIFIED_COPY = "CERTIFIED_COPY"
    NAME_SEARCH = "NAME_SEARCH"


class CopySearchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"
    DENIED = "DENIED"


# --- Entity TypedDicts (all carry the full common-field set) ---
class RecordingOffice(TypedDict):
    id: str
    county_name: str
    book_capacity: int
    instrument_seq_start: int
    next_instrument_number: int
    current_book: int
    current_page: int
    documents_in_current_book: int
    recording_date: str
    daily_collected_cents: int
    total_indexed_entries: int
    created_at: str
    updated_at: str
    version: int


class Submitter(TypedDict):
    id: str
    name: str
    submitter_type: str
    status: str
    escrow_deposited_total_cents: int
    escrow_balance_cents: int
    escrow_held_cents: int
    escrow_available_cents: int
    created_at: str
    updated_at: str
    version: int


class DocumentPackage(TypedDict):
    id: str
    submitter_id: str
    office_id: str
    doc_type: str
    declared_page_count: int
    verified_page_count: Optional[int]
    declared_consideration_cents: int
    verified_consideration_cents: Optional[int]
    first_page_top_margin_inches: float
    notary_present: bool
    status: str
    examiner_user_id: Optional[str]
    resubmission_count: int
    created_at: str
    updated_at: str
    version: int


class PartyEntry(TypedDict):
    id: str
    package_id: str
    party_role: str
    party_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    package_id: str
    recording_fee_cents: int
    transfer_tax_cents: int
    records_mgmt_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    package_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecordedDocument(TypedDict):
    id: str
    package_id: str
    instrument_number: int
    book: int
    page: int
    recorded_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RejectionNotice(TypedDict):
    id: str
    package_id: str
    reason_code: str
    detail: Optional[str]
    cured: bool
    created_at: str
    updated_at: str
    version: int


class PlatSurvey(TypedDict):
    id: str
    submitter_id: str
    office_id: str
    subdivision_name: str
    block_number: int
    start_lot: int
    end_lot: int
    status: str
    plat_book: Optional[int]
    plat_page: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LienUccFiling(TypedDict):
    id: str
    submitter_id: str
    office_id: str
    lien_type: str
    parcel_id: str
    debtor_name: str
    effective_date: str
    lapse_date: str
    continuation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CopySearchRequest(TypedDict):
    id: str
    submitter_id: str
    request_type: str
    recorded_document_id: Optional[str]
    search_name: Optional[str]
    fee_cents: int
    status: str
    result_count: Optional[int]
    created_at: str
    updated_at: str
    version: int
