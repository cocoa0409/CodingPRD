"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ADVERTISER = "Advertiser"
    PUBLISHER = "Publisher"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class NoticeType(str, Enum):
    FORECLOSURE = "FORECLOSURE"
    PROBATE = "PROBATE"
    BID = "BID"


class PricingBasis(str, Enum):
    PER_LINE = "PER_LINE"
    PER_WORD = "PER_WORD"


class AccountType(str, Enum):
    LAW_FIRM = "LAW_FIRM"
    GOVERNMENT = "GOVERNMENT"
    INDIVIDUAL = "INDIVIDUAL"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PROOF_APPROVED = "PROOF_APPROVED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PUBLISHED = "PUBLISHED"
    AFFIDAVIT_ISSUED = "AFFIDAVIT_ISSUED"
    ARCHIVED = "ARCHIVED"


class ComplianceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class InsertionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class ProofStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AffidavitStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    VOID = "VOID"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Newspaper(TypedDict):
    id: str
    name: str
    county: str
    circulation_qualified: bool
    pricing_basis: str
    chars_per_line: int
    line_rate_first_cents: int
    line_rate_subsequent_cents: int
    word_rate_cents: int
    affidavit_fee_cents: int
    edition_line_capacity: int
    publication_weekday: int
    blackout_dates: list
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    name: str
    account_type: str
    credit_limit_cents: int
    status: str
    outstanding_balance_cents: float
    committed_balance_cents: float
    created_at: str
    updated_at: str
    version: int


class StatutoryRequirement(TypedDict):
    id: str
    notice_type: str
    county: str
    min_insertions: int
    min_days_before_deadline: int
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict):
    id: str
    account_id: str
    newspaper_id: str
    notice_type: str
    county: str
    title: str
    body_text: str
    deadline_date: str
    status: str
    word_count: int
    line_count: int
    required_insertions: int
    insertions_published: int
    paid_insertion_count: int
    estimated_cost_cents: int
    final_cost_cents: Optional[int]
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class Insertion(TypedDict):
    id: str
    notice_id: str
    newspaper_id: str
    scheduled_date: str
    sequence_number: int
    status: str
    published_date: Optional[str]
    line_count_actual: Optional[int]
    cost_cents: int
    is_make_good: bool
    makes_good_insertion_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict):
    id: str
    notice_id: str
    status: str
    proof_text: str
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Affidavit(TypedDict):
    id: str
    notice_id: str
    status: str
    publication_dates: list
    sworn_by: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    notice_id: str
    status: str
    subtotal_cents: int
    affidavit_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger records (common_fields: false — only id + created_at) ---

class InvoiceLineItem(TypedDict):
    id: str
    invoice_id: str
    insertion_id: Optional[str]
    description: str
    line_count: int
    rate_cents: int
    amount_cents: int
    created_at: str


class Payment(TypedDict):
    id: str
    account_id: str
    invoice_id: str
    amount_cents: int
    created_at: str
