"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity definitions, state machines, and role catalogue.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ────────────────────────────────────────────────────────────

class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClientStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DebtorStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INSOLVENT = "INSOLVENT"


class RelationshipNoticeStatus(str, Enum):
    PENDING = "PENDING"
    NOTICED = "NOTICED"
    SUSPENDED = "SUSPENDED"


class RecourseType(str, Enum):
    RECOURSE = "RECOURSE"
    NON_RECOURSE = "NON_RECOURSE"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    FUNDED = "FUNDED"
    OUTSTANDING = "OUTSTANDING"
    SHORT_PAID = "SHORT_PAID"
    SETTLED = "SETTLED"
    BOUGHT_BACK = "BOUGHT_BACK"
    WRITTEN_OFF = "WRITTEN_OFF"
    REJECTED = "REJECTED"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    DPD_1_30 = "DPD_1_30"
    DPD_31_60 = "DPD_31_60"
    DPD_61_90 = "DPD_61_90"
    DPD_90_PLUS = "DPD_90_PLUS"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    FUNDED = "FUNDED"
    FAILED = "FAILED"


class VerificationMethod(str, Enum):
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    PORTAL = "PORTAL"
    WAIVED = "WAIVED"


class PostingStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class Payer(str, Enum):
    DEBTOR = "DEBTOR"
    CLIENT = "CLIENT"


class AdjustmentType(str, Enum):
    DILUTION = "DILUTION"
    CREDIT_MEMO = "CREDIT_MEMO"
    CHARGEBACK_FEE = "CHARGEBACK_FEE"


class BuybackTriggerReason(str, Enum):
    RECOURSE_OVERDUE = "RECOURSE_OVERDUE"
    DEBTOR_DISPUTE = "DEBTOR_DISPUTE"
    CLIENT_REQUEST = "CLIENT_REQUEST"


class BuybackStatus(str, Enum):
    COMPLETED = "COMPLETED"


class CreditRating(str, Enum):
    AAA = "AAA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    C = "C"


class LedgerEntryType(str, Enum):
    ADVANCE_DISBURSED = "ADVANCE_DISBURSED"
    RESERVE_HELD = "RESERVE_HELD"
    FEE_ACCRUED = "FEE_ACCRUED"
    COLLECTION_POSTED = "COLLECTION_POSTED"
    REBATE_PAID = "REBATE_PAID"
    RESERVE_RELEASED = "RESERVE_RELEASED"
    BUYBACK_RECEIVED = "BUYBACK_RECEIVED"
    WRITE_OFF = "WRITE_OFF"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    UNDERWRITING_OFFICER = "UnderwritingOfficer"
    FUNDING_OFFICER = "FundingOfficer"
    COLLECTIONS_OFFICER = "CollectionsOfficer"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# common_fields: true entities carry id, created_at, updated_at, version.
# common_fields: false entities (Verification, LedgerEntry) carry ONLY
# id + created_at — no updated_at, no version.

class FactoringProgram(TypedDict):
    id: str
    name: str
    currency: str
    default_fee_rate_per_day: float
    tier2_multiplier: float
    tier3_multiplier: float
    recourse_grace_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    program_id: str
    legal_name: str
    requested_advance_rate_pct: float
    approved_advance_rate_pct: Optional[float]
    credit_limit_cents: Optional[int]
    default_concentration_limit_pct: Optional[float]
    reserve_balance_cents: int
    funded_advance_outstanding_cents: int
    credit_decision_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Debtor(TypedDict):
    id: str
    program_id: str
    legal_name: str
    credit_rating: str
    approved_credit_ceiling_cents: Optional[int]
    verification_required: bool
    outstanding_face_cents: int
    credit_decision_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClientDebtorRelationship(TypedDict):
    id: str
    client_id: str
    debtor_id: str
    recourse_type: str
    concentration_limit_pct: Optional[float]
    notice_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    client_id: str
    debtor_id: str
    relationship_id: Optional[str]
    invoice_number: str
    face_amount_cents: int
    issue_date: str
    due_date: str
    advance_rate_pct: Optional[float]
    fee_rate_per_day: Optional[float]
    advance_amount_cents: int
    reserve_held_cents: int
    amount_collected_cents: int
    dilution_cents: int
    advance_outstanding_cents: int
    accrued_fee_cents: int
    final_fee_cents: Optional[int]
    funded_at: Optional[str]
    aging_bucket: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseBatch(TypedDict):
    id: str
    client_id: str
    batch_reference: str
    invoice_ids: List[str]
    total_advance_cents: int
    failure_error_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Verification(TypedDict):
    # common_fields: false — only id + created_at (no updated_at, no version)
    id: str
    invoice_id: str
    method: str
    confirmed_amount_cents: int
    notice_of_assignment_sent: bool
    verified_at: Optional[str]
    created_at: str


class CollectionPosting(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    received_at: str
    payer: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Adjustment(TypedDict):
    id: str
    invoice_id: str
    type: str
    amount_cents: int
    reason: str
    created_at: str
    updated_at: str
    version: int


class Buyback(TypedDict):
    id: str
    invoice_id: str
    trigger_reason: str
    buyback_amount_cents: int
    reserve_released_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    invoice_id: str
    collected_total_cents: int
    principal_applied_cents: int
    fee_applied_cents: int
    rebate_cents: int
    fee_shortfall_cents: int
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    # common_fields: false — only id + created_at (no updated_at, no version)
    id: str
    client_id: str
    invoice_id: Optional[str]
    entry_type: str
    amount_cents: int
    reserve_balance_after_cents: int
    created_at: str
