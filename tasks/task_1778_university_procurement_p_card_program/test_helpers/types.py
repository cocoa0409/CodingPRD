"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    REQUESTER = "Requester"
    DEPARTMENT_APPROVER = "DepartmentApprover"
    BUYER = "Buyer"
    PROCUREMENT_DIRECTOR = "ProcurementDirector"
    CONTRACT_OFFICER = "ContractOfficer"
    GRANT_OFFICER = "GrantOfficer"
    AP_CLERK = "APClerk"
    RECEIVING_CLERK = "ReceivingClerk"
    CARDHOLDER = "Cardholder"
    SURPLUS_MANAGER = "SurplusManager"
    PROCUREMENT_ADMIN = "ProcurementAdmin"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"
    SUPERSEDED = "SUPERSEDED"


class RequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    PO_ISSUED = "PO_ISSUED"
    CANCELLED = "CANCELLED"


class ChainStep(str, Enum):
    DEPARTMENT = "DEPARTMENT"
    GRANT_COMPLIANCE = "GRANT_COMPLIANCE"
    SOLE_SOURCE = "SOLE_SOURCE"
    PURCHASING = "PURCHASING"
    DIRECTOR = "DIRECTOR"
    CONTRACT_REVIEW = "CONTRACT_REVIEW"


class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class SolicitationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    NOT_AWARDED = "NOT_AWARDED"
    DISQUALIFIED = "DISQUALIFIED"


class FulfillmentStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FULLY_RECEIVED = "FULLY_RECEIVED"
    CANCELLED = "CANCELLED"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"
    CLOSED = "CLOSED"


class ReceiptStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    PAYABLE = "PAYABLE"
    EXCEPTION = "EXCEPTION"
    PAID = "PAID"
    REJECTED = "REJECTED"


class ExceptionReason(str, Enum):
    NONE = "NONE"
    NO_RECEIPT = "NO_RECEIPT"
    QTY_OVER_RECEIPT = "QTY_OVER_RECEIPT"
    PRICE_VARIANCE = "PRICE_VARIANCE"
    CONTRACT_TERMINATED = "CONTRACT_TERMINATED"
    RECEIPT_VOIDED = "RECEIPT_VOIDED"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ElevationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    REVERSED = "REVERSED"


class EntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AllocationType(str, Enum):
    GENERAL = "GENERAL"
    GRANT = "GRANT"


class CostCategory(str, Enum):
    SUPPLIES = "SUPPLIES"
    EQUIPMENT = "EQUIPMENT"
    TRAVEL = "TRAVEL"
    SERVICES = "SERVICES"
    SOFTWARE = "SOFTWARE"


class SourcingMethod(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    EXISTING_CONTRACT = "EXISTING_CONTRACT"
    SOLE_SOURCE = "SOLE_SOURCE"
    COMPETITIVE_BID = "COMPETITIVE_BID"


class AssetCondition(str, Enum):
    NEW = "NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class SurplusStatus(str, Enum):
    DECLARED = "DECLARED"
    LISTED = "LISTED"
    TRANSFERRED = "TRANSFERRED"
    SOLD = "SOLD"
    DONATED = "DONATED"
    SCRAPPED = "SCRAPPED"


class DisputeOutcome(str, Enum):
    CARDHOLDER_FAVOR = "CARDHOLDER_FAVOR"
    MERCHANT_FAVOR = "MERCHANT_FAVOR"


class ResolutionAction(str, Enum):
    ACCEPT_VARIANCE = "ACCEPT_VARIANCE"
    REJECT_INVOICE = "REJECT_INVOICE"


# --- Entity TypedDicts -------------------------------------------------------
# Every primary resource carries id/created_at/updated_at/version (PRD §2.5);
# the approval audit record carries only id + created_at.


class Department(TypedDict, total=False):
    id: str
    name: str
    cost_center: str
    diversity_goal_pct: float
    sustainability_goal_pct: float
    default_approval_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    legal_name: str
    diversity_certification: str
    sustainability_tier: str
    payment_terms_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    grant_code: str
    sponsor: str
    total_award_cents: int
    f_and_a_rate: float
    equipment_cap_cents: int
    allowed_categories: List[str]
    budget_start: str
    budget_end: str
    status: str
    spent_cents: int
    encumbered_cents: int
    provisional_remaining_cents: int
    settled_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    vendor_id: str
    commodity_code: str
    value_cents: int
    effective_start: str
    effective_end: str
    terms_text: str
    status: str
    negotiation_round: int
    supersedes_contract_id: Optional[str]
    executed_at: Optional[str]
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RequisitionLine(TypedDict, total=False):
    line_no: int
    commodity_code: str
    description: str
    quantity: int
    unit_price_cents: int
    cost_category: str


class Requisition(TypedDict, total=False):
    id: str
    requisition_number: str
    department_id: str
    requester_id: str
    vendor_id: Optional[str]
    grant_id: Optional[str]
    contract_id: Optional[str]
    lines: List[RequisitionLine]
    total_cents: int
    has_grant_funding: bool
    charge_cents: int
    sole_source_requested: bool
    sole_source_justification: Optional[str]
    sole_source_approved: bool
    sourcing_method: str
    required_chain: List[str]
    current_step_index: int
    status: str
    submitted_at: Optional[str]
    returned_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalRecord(TypedDict, total=False):
    id: str
    requisition_id: str
    step_index: int
    step_role: str
    actor_id: str
    decision: str
    reason: Optional[str]
    decided_at: str
    created_at: str
    # NOTE: no updated_at, no version — immutable audit record (PRD §2.5)


class BidSolicitation(TypedDict, total=False):
    id: str
    requisition_id: str
    response_deadline: str
    min_quotes: int
    status: str
    awarded_quote_id: Optional[str]
    awarded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    solicitation_id: str
    vendor_id: str
    price_cents: int
    submitted_at: str
    status: str
    score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    po_number: str
    requisition_id: str
    vendor_id: str
    contract_id: Optional[str]
    grant_id: Optional[str]
    lines: List[RequisitionLine]
    total_cents: int
    charge_cents: int
    contract_version_pinned: Optional[int]
    fulfillment_status: str
    match_status: str
    contract_terminated_flag: bool
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict, total=False):
    id: str
    po_id: str
    lines: List[dict]
    received_by: str
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    po_id: str
    vendor_id: str
    invoice_number: str
    lines: List[dict]
    total_cents: int
    total_variance_cents: int
    total_tolerance_cents: int
    status: str
    exception_reason: str
    variance_accepted_by: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PCard(TypedDict, total=False):
    id: str
    department_id: str
    cardholder_name: str
    single_txn_limit_cents: int
    monthly_limit_cents: int
    allowed_mccs: List[str]
    status: str
    cycle_index: int
    consecutive_unreconciled_cycles: int
    utilization_cents: int
    available_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class LimitElevation(TypedDict, total=False):
    id: str
    pcard_id: str
    elevated_single_txn_limit_cents: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PCardTransaction(TypedDict, total=False):
    id: str
    pcard_id: str
    amount_cents: int
    entry_type: str
    merchant_name: str
    mcc_code: str
    posted_at: str
    cycle_index: int
    status: str
    pre_dispute_status: Optional[str]
    receipt_reference: Optional[str]
    allocation_type: Optional[str]
    grant_id: Optional[str]
    cost_category: Optional[str]
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurplusAsset(TypedDict, total=False):
    id: str
    asset_tag: str
    department_id: str
    description: str
    condition: str
    estimated_value_cents: int
    disposal_cost_cents: int
    status: str
    declared_at: str
    claiming_department_id: Optional[str]
    sale_price_cents: Optional[int]
    buyer_name: Optional[str]
    recipient_name: Optional[str]
    proceeds_cost_recovery_cents: Optional[int]
    proceeds_dept_share_cents: Optional[int]
    proceeds_central_share_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BudgetLedger(TypedDict, total=False):
    spent_cents: int
    encumbered_cents: int
    provisional_remaining_cents: int
    settled_remaining_cents: int


class DiversityReport(TypedDict, total=False):
    basis: str
    diverse_spend_cents: int
    total_spend_cents: int
    ratio: float
    goal_met: bool
