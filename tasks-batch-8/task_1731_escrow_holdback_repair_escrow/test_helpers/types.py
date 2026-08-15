"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class EscrowFileStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class HoldbackStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVALS = "PENDING_APPROVALS"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CLOSED_COMPLETED = "CLOSED_COMPLETED"
    CLOSED_EXPIRED = "CLOSED_EXPIRED"


class ApprovalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"


class ApproverRole(str, Enum):
    LENDER = "LENDER"
    INSURER = "INSURER"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class WorkOrderStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETION_SUBMITTED = "COMPLETION_SUBMITTED"
    VERIFIED = "VERIFIED"


class InspectionStatus(str, Enum):
    PLANNED = "PLANNED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionPurpose(str, Enum):
    DRAW_VERIFICATION = "DRAW_VERIFICATION"
    FINAL_VERIFICATION = "FINAL_VERIFICATION"
    REINSPECTION = "REINSPECTION"


class DrawStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class ExtensionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class ExtensionReason(str, Enum):
    WEATHER_EXTERIOR = "WEATHER_EXTERIOR"
    SUPPLY_DELAY = "SUPPLY_DELAY"
    OTHER = "OTHER"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_BUYER = "RESOLVED_BUYER"
    RESOLVED_SELLER = "RESOLVED_SELLER"
    RESOLVED_SPLIT = "RESOLVED_SPLIT"


class PledgeStatus(str, Enum):
    PLEDGED = "PLEDGED"
    DEPOSITED = "DEPOSITED"


class LedgerEntryType(str, Enum):
    FUNDING = "FUNDING"
    DRAW_DEBIT = "DRAW_DEBIT"
    SHORTFALL_DEPOSIT = "SHORTFALL_DEPOSIT"
    RETURN_TO_SELLER = "RETURN_TO_SELLER"
    RELEASE_TO_BUYER = "RELEASE_TO_BUYER"
    REFUND_TO_SOURCE = "REFUND_TO_SOURCE"


class FundingSource(str, Enum):
    SELLER_PROCEEDS = "SELLER_PROCEEDS"
    BUYER_DEPOSIT = "BUYER_DEPOSIT"
    SPLIT_EQUAL = "SPLIT_EQUAL"


class OverrunResponsibility(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    SPLIT_EQUAL = "SPLIT_EQUAL"


class ExpirationTerms(str, Enum):
    RETURN_TO_SELLER = "RETURN_TO_SELLER"
    RELEASE_TO_BUYER = "RELEASE_TO_BUYER"
    SPLIT_EQUAL = "SPLIT_EQUAL"


class UserRole(str, Enum):
    ESCROW_OFFICER = "EscrowOfficer"
    BUYER = "Buyer"
    SELLER = "Seller"
    LENDER = "Lender"
    INSURER = "Insurer"
    CONTRACTOR = "Contractor"
    INSPECTOR = "Inspector"


class EscrowFile(TypedDict, total=False):
    id: str
    property_address: str
    closing_date: str
    buyer_user_id: str
    seller_user_id: str
    lender_user_id: str
    insurer_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Holdback(TypedDict, total=False):
    id: str
    escrow_file_id: str
    repair_scope: str
    repair_estimate_cents: int
    contingency_pct: int
    holdback_amount_cents: int
    commitment_basis_cents: Optional[int]
    funding_source: str
    overrun_responsibility: str
    expiration_terms: str
    work_deadline_date: str
    hard_stop_date: str
    exterior_work_flag: bool
    granted_extension_days: int
    effective_deadline_date: str
    lender_approval_required: bool
    insurer_approval_required: bool
    selected_bid_id: Optional[str]
    status: str
    trust_balance_cents: int
    reserved_cents: int
    total_disbursed_cents: int
    total_shortfall_deposited_cents: int
    work_verified: bool
    disbursement_frozen: bool
    closeout_status: str
    disposition_override: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Approval(TypedDict, total=False):
    id: str
    holdback_id: str
    approver_role: str
    status: str
    approver_user_id: Optional[str]
    holdback_version_at_decision: Optional[int]
    decided_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    holdback_id: str
    contractor_user_id: str
    amount_cents: int
    scope_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    holdback_id: str
    contractor_user_id: str
    agreed_amount_cents: int
    started_at: str
    completion_deadline_date: str
    status: str
    failed_final_count: int
    submitted_completion_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    holdback_id: str
    inspector_user_id: str
    purpose: str
    scheduled_start: str
    scheduled_end: str
    status: str
    reported_at: Optional[str]
    result_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrawRequest(TypedDict, total=False):
    id: str
    holdback_id: str
    contractor_user_id: str
    amount_cents: int
    description: str
    is_final: bool
    status: str
    approved_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict, total=False):
    id: str
    holdback_id: str
    requester_user_id: str
    reason: str
    requested_days: int
    evidence_ref: str
    status: str
    granted_days: Optional[int]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    holdback_id: str
    initiator_role: str
    initiator_user_id: str
    category: str
    claimed_amount_cents: int
    statement: str
    status: str
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShortfallPledge(TypedDict, total=False):
    id: str
    holdback_id: str
    payer_role: str
    payer_user_id: str
    amount_cents: int
    status: str
    deposited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: carries ONLY id + created_at from the common set
# (PRD §2.5: both updated_at and version are absent from a ledger entry).
class LedgerEntry(TypedDict, total=False):
    id: str
    holdback_id: str
    seq: int
    entry_type: str
    amount_cents: int
    running_balance_cents: int
    memo: str
    created_at: str
