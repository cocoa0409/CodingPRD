"""Domain types: entity TypedDicts, status enums, role enum for the Title Insurance Escrow API."""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    AGENCY = "Agency"
    TITLE_OFFICER = "TitleOfficer"
    UNDERWRITER = "Underwriter"


# --- Status enums ---
class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OrderStatus(str, Enum):
    OPENED = "OPENED"
    IN_TITLE = "IN_TITLE"
    COMMITTED = "COMMITTED"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TitleSearchStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_EXAM = "IN_EXAM"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    UPDATED = "UPDATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ExceptionStatus(str, Enum):
    RAISED = "RAISED"
    CURATIVE_PENDING = "CURATIVE_PENDING"
    WAIVED = "WAIVED"
    CLEARED = "CLEARED"
    VOID = "VOID"


class PolicyStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    VOID = "VOID"


class EndorsementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ATTACHED = "ATTACHED"
    REMOVED = "REMOVED"


class EscrowDepositStatus(str, Enum):
    RECEIVED = "RECEIVED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    WIRED = "WIRED"
    VOID = "VOID"


class PremiumRemittanceStatus(str, Enum):
    PENDING = "PENDING"
    REMITTED = "REMITTED"
    REVERSED = "REVERSED"


class ClaimStatus(str, Enum):
    FNOL = "FNOL"
    INVESTIGATING = "INVESTIGATING"
    CURATIVE = "CURATIVE"
    PAID = "PAID"
    DENIED = "DENIED"


class CurativeActionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ABANDONED = "ABANDONED"


# --- Enumerated input value sets ---
class TransactionType(str, Enum):
    PURCHASE = "PURCHASE"
    REFINANCE = "REFINANCE"
    REISSUE = "REISSUE"


class InstrumentType(str, Enum):
    DEED = "DEED"
    MORTGAGE = "MORTGAGE"
    LIEN = "LIEN"
    EASEMENT = "EASEMENT"
    RELEASE = "RELEASE"


class ScheduleAEstate(str, Enum):
    FEE_SIMPLE = "FEE_SIMPLE"
    LEASEHOLD = "LEASEHOLD"


class ExceptionType(str, Enum):
    STANDARD = "STANDARD"
    SPECIAL = "SPECIAL"
    SUBORDINATE_LIEN = "SUBORDINATE_LIEN"


class PolicyType(str, Enum):
    OWNER = "OWNER"
    LENDER = "LENDER"


class EndorsementFormCode(str, Enum):
    ENV_PROTECTION = "ENV_PROTECTION"
    ZONING = "ZONING"
    SURVEY = "SURVEY"
    RESTRICTIONS = "RESTRICTIONS"


class DisbursementPurpose(str, Enum):
    SELLER_PROCEEDS = "SELLER_PROCEEDS"
    PAYOFF = "PAYOFF"
    PREMIUM = "PREMIUM"
    RECORDING_FEE = "RECORDING_FEE"
    CLAIM_PAYOUT = "CLAIM_PAYOUT"


class ClaimType(str, Enum):
    UNDISCLOSED_LIEN = "UNDISCLOSED_LIEN"
    BOUNDARY_DISPUTE = "BOUNDARY_DISPUTE"
    FORGERY = "FORGERY"
    ACCESS_DEFECT = "ACCESS_DEFECT"


class CurativeActionType(str, Enum):
    PAYOFF = "PAYOFF"
    RELEASE_FILED = "RELEASE_FILED"
    QUIET_TITLE = "QUIET_TITLE"
    INDEMNITY = "INDEMNITY"


class CurativeSubjectType(str, Enum):
    EXCEPTION = "EXCEPTION"
    CLAIM = "CLAIM"


# --- Entity TypedDicts ---
# Entities with the full audit triple (created_at + updated_at + version).
class Agency(TypedDict):
    id: str
    name: str
    remit_split_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


# TitlePlantRecord is the ONLY entity with no audit triple: id + created_at only.
class TitlePlantRecord(TypedDict):
    id: str
    parcel_id: str
    county: str
    instrument_type: str
    recorded_date: str
    sequence_no: int
    grantor: str
    grantee: str
    created_at: str


class Order(TypedDict):
    id: str
    agency_id: str
    parcel_id: str
    county: str
    transaction_type: str
    sales_price_cents: int
    loan_amount_cents: int
    status: str
    escrow_deposit_total_cents: int
    escrow_disbursed_total_cents: int
    escrow_balance_cents: int
    gap_open: bool
    created_at: str
    updated_at: str
    version: int


class TitleSearch(TypedDict):
    id: str
    order_id: str
    searched_parcel_id: str
    effective_date: str
    status: str
    chain_verified: bool
    gap_from_date: Optional[str]
    gap_to_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Commitment(TypedDict):
    id: str
    order_id: str
    effective_date: str
    expiry_date: str
    schedule_a_estate: str
    insured_amount_cents: int
    status: str
    open_exception_count: int
    revision_no: int
    created_at: str
    updated_at: str
    version: int


class Exception(TypedDict):
    id: str
    commitment_id: str
    exception_type: str
    description: str
    curative_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    order_id: str
    commitment_id: str
    policy_type: str
    coverage_amount_cents: int
    is_reissue: bool
    co_issued_with_owner: bool
    gross_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    policy_id: str
    form_code: str
    charge_pct: float
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowDeposit(TypedDict):
    id: str
    order_id: str
    amount_cents: int
    source_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    order_id: str
    payee: str
    amount_cents: int
    purpose: str
    status: str
    wire_window_start: str
    wire_window_end: str
    created_at: str
    updated_at: str
    version: int


class PremiumRemittance(TypedDict):
    id: str
    policy_id: str
    gross_premium_cents: int
    agency_retained_cents: int
    underwriter_remit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    claim_type: str
    estimated_loss_cents: int
    reserve_cents: int
    settled_loss_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CurativeAction(TypedDict):
    id: str
    order_id: str
    subject_type: str
    subject_id: str
    action_type: str
    status: str
    created_at: str
    updated_at: str
    version: int
