"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in PRD §2.4 and the workflows of PRD §3.
The append-only RecoveryLedgerEntry (PRD §2.4) carries only id + created_at;
every other resource carries the full standard set (id, created_at,
updated_at, version).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    RECOVERY_MANAGER = "RecoveryManager"
    REPO_AGENT = "RepoAgent"
    AUCTIONEER = "Auctioneer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BORROWER = "Borrower"


class LoanAccountStatus(str, Enum):
    CURRENT = "CURRENT"
    IN_DEFAULT = "IN_DEFAULT"
    REDEEMED_PAID = "REDEEMED_PAID"
    CHARGED_OFF = "CHARGED_OFF"


class RecoveryCaseStatus(str, Enum):
    OPENED = "OPENED"
    CURE_PENDING = "CURE_PENDING"
    CURED = "CURED"
    CURE_EXPIRED = "CURE_EXPIRED"
    REPO_ACTIVE = "REPO_ACTIVE"
    COLLATERAL_SECURED = "COLLATERAL_SECURED"
    REDEMPTION_OPEN = "REDEMPTION_OPEN"
    REDEEMED = "REDEEMED"
    REINSTATED = "REINSTATED"
    CONSIGNMENT_PENDING = "CONSIGNMENT_PENDING"
    IN_AUCTION = "IN_AUCTION"
    SALE_CONFIRMED = "SALE_CONFIRMED"
    DEFICIENCY_NOTICED = "DEFICIENCY_NOTICED"
    COMPLAINT_REVIEW = "COMPLAINT_REVIEW"
    RESTITUTION = "RESTITUTION"
    CLOSED = "CLOSED"


class CureNoticeStatus(str, Enum):
    SENT = "SENT"
    CURED = "CURED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class RepoAgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RepoAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    SECURED = "SECURED"
    BREACHED_PEACE = "BREACHED_PEACE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PersonalPropertyItemStatus(str, Enum):
    INVENTORIED = "INVENTORIED"
    CLAIMED = "CLAIMED"
    RETURNED = "RETURNED"
    DISPOSED = "DISPOSED"


class QuoteType(str, Enum):
    REDEMPTION = "REDEMPTION"
    REINSTATEMENT = "REINSTATEMENT"


class RedemptionQuoteStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class ConsignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    UNSOLD = "UNSOLD"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


class SaleRecordStatus(str, Enum):
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    CERTIFIED = "CERTIFIED"
    VOID = "VOID"


class DeficiencyNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    VOID = "VOID"


class ComplaintCategory(str, Enum):
    WRONGFUL_REPOSSESSION = "WRONGFUL_REPOSSESSION"
    BREACH_OF_PEACE = "BREACH_OF_PEACE"
    PROPERTY_LOSS = "PROPERTY_LOSS"
    DEFICIENCY_DISPUTE = "DEFICIENCY_DISPUTE"
    NOTICE_DEFECT = "NOTICE_DEFECT"


class ComplaintStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class LedgerEntryKind(str, Enum):
    COST_REPO_FEE = "COST_REPO_FEE"
    COST_STORAGE = "COST_STORAGE"
    COST_TRANSPORT = "COST_TRANSPORT"
    COST_KEY = "COST_KEY"
    COST_OTHER = "COST_OTHER"
    ADJUSTMENT = "ADJUSTMENT"
    PAYMENT = "PAYMENT"
    REVERSAL = "REVERSAL"
    REFUND = "REFUND"


# ---------------------------------------------------------------------------
# Entity TypedDicts (standard common fields: id, created_at, updated_at,
# version — except the append-only ledger entry)
# ---------------------------------------------------------------------------

class Borrower(TypedDict, total=False):
    id: str
    full_name: str
    state_code: str
    email: str
    created_at: str
    updated_at: str
    version: int


class LoanAccount(TypedDict, total=False):
    id: str
    borrower_id: str
    vin: str
    governing_state_code: str
    principal_balance_cents: int
    apr_bps: int
    monthly_payment_cents: int
    missed_installments: int
    accrued_interest_cents: int
    late_fees_cents: int
    paid_to_date_cents: int
    total_outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryCase(TypedDict, total=False):
    id: str
    loan_account_id: str
    default_reason: str
    opened_by_user_id: str
    status: str
    cure_deadline: Optional[str]
    redemption_deadline: Optional[str]
    pre_complaint_state: Optional[str]
    current_cure_notice_id: Optional[str]
    current_redemption_quote_id: Optional[str]
    collateral_secured_at: Optional[str]
    odometer: Optional[int]
    condition_grade: Optional[str]
    trade_in_value_cents: Optional[int]
    auction_guide_low_cents: Optional[int]
    sold_at: Optional[str]
    property_item_count: int
    created_at: str
    updated_at: str
    version: int


class CureNotice(TypedDict, total=False):
    id: str
    recovery_case_id: str
    status: str
    sent_at: str
    cure_amount_cents: int
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepoAgent(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    licensed_state_codes: List[str]
    max_active_assignments: int
    status: str
    performance_score_lifetime: int
    performance_score_rolling: int
    created_at: str
    updated_at: str
    version: int


class RepoAssignment(TypedDict, total=False):
    id: str
    recovery_case_id: str
    agent_id: str
    status: str
    field_window_start: str
    field_window_end: str
    auto_selected: bool
    secured_fast: bool
    created_at: str
    updated_at: str
    version: int


class PersonalPropertyItem(TypedDict, total=False):
    id: str
    recovery_case_id: str
    description: str
    estimated_value_cents: int
    status: str
    claimed_by_borrower_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RedemptionQuote(TypedDict, total=False):
    id: str
    recovery_case_id: str
    quote_type: str
    status: str
    issued_at: str
    valid_until: str
    quoted_amount_cents: int
    per_diem_cents: int
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuctionHouse(TypedDict, total=False):
    id: str
    name: str
    fee_bps: int
    transport_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict, total=False):
    id: str
    recovery_case_id: str
    auction_house_id: str
    status: str
    reserve_price_cents: int
    listing_start: Optional[str]
    listing_end: Optional[str]
    relist_count: int
    consignment_seq: int
    created_at: str
    updated_at: str
    version: int


class SaleRecord(TypedDict, total=False):
    id: str
    consignment_id: str
    gross_sale_cents: int
    auction_fee_cents: int
    transport_fee_cents: int
    net_proceeds_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeficiencyNotice(TypedDict, total=False):
    id: str
    recovery_case_id: str
    status: str
    deficiency_amount_cents: int
    surplus_cents: int
    paid_cents: int
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    recovery_case_id: str
    borrower_id: str
    category: str
    description: str
    status: str
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryLedgerEntry(TypedDict, total=False):
    """Append-only ledger row (PRD §2.4): id + created_at only, no
    updated_at, no version, and no update/delete endpoint exists."""
    id: str
    recovery_case_id: str
    kind: str
    amount_cents: int
    memo: str
    reverses_entry_id: Optional[str]
    created_at: str
