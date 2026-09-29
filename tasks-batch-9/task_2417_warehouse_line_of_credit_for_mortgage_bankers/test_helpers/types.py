"""Domain types for the Warehouse Lending Facility API.

Status enums, role enum and entity TypedDicts. Field names are exactly as the
PRD spells them.

Two resources are append-only records rather than mutable entities: a
``CurePayment`` and a ``LedgerEntry`` carry only ``id`` and ``created_at`` —
neither has an ``updated_at`` and neither has a ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────────────

class UserRole(str, Enum):
    CREDIT_OFFICER = "CreditOfficer"
    COLLATERAL_ANALYST = "CollateralAnalyst"
    WIRE_OPERATOR = "WireOperator"
    BORROWER = "Borrower"
    CUSTODIAN = "Custodian"
    INVESTOR = "Investor"


# ─── Status enums ─────────────────────────────────────────────────────────────

class FacilityStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class CovenantPosture(str, Enum):
    """The facility's ``last_covenant_status`` projection."""

    NOT_TESTED = "NOT_TESTED"
    PASS = "PASS"
    BREACH = "BREACH"
    WAIVED = "WAIVED"


class CustodianStatus(str, Enum):
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class InvestorStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class CommitmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class AdvanceFundingStatus(str, Enum):
    """The money axis of the advance's parallel state machine."""

    REQUESTED = "REQUESTED"
    FUNDED = "FUNDED"
    SHIPPED = "SHIPPED"
    PURCHASED = "PURCHASED"
    REPURCHASED = "REPURCHASED"
    REJECTED = "REJECTED"


class AdvanceCustodyStatus(str, Enum):
    """The collateral-file axis of the advance's parallel state machine."""

    PENDING_RECEIPT = "PENDING_RECEIPT"
    RECEIVED_CLEAR = "RECEIVED_CLEAR"
    RECEIVED_EXCEPTION = "RECEIVED_EXCEPTION"
    EXCEPTION_CURED = "EXCEPTION_CURED"
    RECEIPT_OVERDUE = "RECEIPT_OVERDUE"
    RELEASED_TO_INVESTOR = "RELEASED_TO_INVESTOR"


class WireInstructionStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    RELEASED = "RELEASED"


class ReceiptStatus(str, Enum):
    CLEAR = "CLEAR"
    EXCEPTION = "EXCEPTION"
    CURED = "CURED"


class BaileeLetterStatus(str, Enum):
    ISSUED = "ISSUED"
    HONORED = "HONORED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class MarginCallStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_CURED = "PARTIALLY_CURED"
    CURED = "CURED"
    WAIVED = "WAIVED"
    DEFAULTED = "DEFAULTED"


class CovenantTestStatus(str, Enum):
    PASS = "PASS"
    BREACH = "BREACH"
    WAIVED = "WAIVED"


class RepurchaseDemandStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    SATISFIED = "SATISFIED"


# ─── Value enums ──────────────────────────────────────────────────────────────

class ProductCode(str, Enum):
    CONFORMING = "CONFORMING"
    JUMBO = "JUMBO"
    FHA_VA = "FHA_VA"
    NON_QM = "NON_QM"
    SCRATCH_AND_DENT = "SCRATCH_AND_DENT"


class FundingType(str, Enum):
    WET = "WET"
    DRY = "DRY"


class CounterpartyRating(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class DocumentType(str, Enum):
    NOTE = "NOTE"
    MORTGAGE = "MORTGAGE"
    ASSIGNMENT = "ASSIGNMENT"
    TITLE_POLICY = "TITLE_POLICY"


class ExceptionCode(str, Enum):
    MISSING_NOTE = "MISSING_NOTE"
    UNSIGNED_ASSIGNMENT = "UNSIGNED_ASSIGNMENT"
    STALE_TITLE = "STALE_TITLE"
    NAME_MISMATCH = "NAME_MISMATCH"


class MarginCallTriggerReason(str, Enum):
    VALUATION_DECLINE = "VALUATION_DECLINE"
    COMMITMENT_WITHDRAWN = "COMMITMENT_WITHDRAWN"
    DWELL_EXCEEDED = "DWELL_EXCEEDED"
    CUSTODY_EXCEPTION = "CUSTODY_EXCEPTION"
    COVENANT_BREACH = "COVENANT_BREACH"


class BreachCode(str, Enum):
    LIQUIDITY = "LIQUIDITY"
    NET_WORTH = "NET_WORTH"
    PROFITABILITY = "PROFITABILITY"


class ProfitabilityVariant(str, Enum):
    TTM_ROLLING = "TTM_ROLLING"
    ANNUALIZED_QUARTER = "ANNUALIZED_QUARTER"


class RepurchaseDemandReason(str, Enum):
    DWELL_EXCEEDED = "DWELL_EXCEEDED"
    CUSTODY_EXCEPTION_UNCURED = "CUSTODY_EXCEPTION_UNCURED"
    BAILEE_EXPIRED = "BAILEE_EXPIRED"
    INVESTOR_SUSPENDED = "INVESTOR_SUSPENDED"
    INELIGIBLE_PRODUCT = "INELIGIBLE_PRODUCT"


class RejectedReason(str, Enum):
    WIRE_BLOCKED = "WIRE_BLOCKED"
    FACILITY_SUSPENDED = "FACILITY_SUSPENDED"


class BlockReason(str, Enum):
    OPERATOR_BLOCK = "OPERATOR_BLOCK"
    FACILITY_SUSPENDED = "FACILITY_SUSPENDED"


class LedgerEntryType(str, Enum):
    ADVANCE_FUNDED = "ADVANCE_FUNDED"
    CURE_PRINCIPAL = "CURE_PRINCIPAL"
    INVESTOR_PROCEEDS = "INVESTOR_PROCEEDS"
    REPURCHASE = "REPURCHASE"
    FEE_ACCRUAL = "FEE_ACCRUAL"
    FEE_PAYMENT = "FEE_PAYMENT"
    MARGIN_CALL_WAIVED = "MARGIN_CALL_WAIVED"


class LedgerDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class WireDecision(str, Enum):
    VERIFY = "VERIFY"
    BLOCK = "BLOCK"


#: The four principal-moving ledger entry types (PRD §2.6).
PRINCIPAL_MOVING_ENTRY_TYPES = (
    LedgerEntryType.ADVANCE_FUNDED.value,
    LedgerEntryType.CURE_PRINCIPAL.value,
    LedgerEntryType.INVESTOR_PROCEEDS.value,
    LedgerEntryType.REPURCHASE.value,
)

#: The funding-axis states that count toward every outstanding rollup.
CARRYING_FUNDING_STATUSES = (
    AdvanceFundingStatus.FUNDED.value,
    AdvanceFundingStatus.SHIPPED.value,
)

#: The funding-axis states that are terminal.
TERMINAL_FUNDING_STATUSES = (
    AdvanceFundingStatus.PURCHASED.value,
    AdvanceFundingStatus.REPURCHASED.value,
    AdvanceFundingStatus.REJECTED.value,
)

#: The margin-call states that count as open.
OPEN_MARGIN_CALL_STATUSES = (
    MarginCallStatus.ISSUED.value,
    MarginCallStatus.PARTIALLY_CURED.value,
)


# ─── Entity TypedDicts ────────────────────────────────────────────────────────

class WarehouseFacility(TypedDict):
    id: str
    borrower_legal_name: str
    committed_amount_cents: int
    wet_sublimit_cents: int
    aged_sublimit_cents: int
    scratch_and_dent_sublimit_cents: int
    min_tangible_net_worth_cents: int
    min_liquidity_cents: int
    min_ttm_net_income_cents: int
    max_investor_concentration_pct: float
    unused_line_fee_rate: float
    settlement_account_last4: str
    bailee_period_days: int
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    last_accrual_at: Optional[str]
    outstanding_principal_cents: int
    availability_cents: int
    accrued_fee_balance_cents: int
    wet_outstanding_cents: int
    aged_outstanding_cents: int
    scratch_and_dent_outstanding_cents: int
    open_margin_call_count: int
    consecutive_breach_count: int
    escalated_demand_count: int
    last_covenant_status: str
    created_at: str
    updated_at: str
    version: int


class ProductAdvanceRate(TypedDict):
    id: str
    facility_id: str
    product_code: str
    advance_rate: float
    wet_funding_allowed: bool
    wet_haircut: float
    dwell_limit_days: int
    aging_step_days: int
    curtailment_step_rate: float
    product_sublimit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DocumentCustodian(TypedDict):
    id: str
    facility_id: str
    custodian_name: str
    wet_receipt_deadline_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TakeoutInvestor(TypedDict):
    id: str
    facility_id: str
    investor_name: str
    counterparty_rating: str
    concentration_limit_pct: float
    status: str
    exposure_cents: int
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvestorCommitment(TypedDict):
    id: str
    facility_id: str
    investor_id: str
    product_code: str
    committed_amount_cents: int
    price_pct: float
    effective_on: str
    expires_on: str
    allocated_amount_cents: int
    settled_amount_cents: int
    remaining_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Advance(TypedDict):
    id: str
    facility_id: str
    custodian_id: str
    investor_commitment_id: Optional[str]
    product_code: str
    loan_amount_cents: int
    note_rate: float
    funding_type: str
    payee_name: str
    payee_account_last4: str
    payee_routing_last4: str
    funding_status: str
    custody_status: str
    market_value_cents: int
    provisional_advance_amount_cents: int
    advance_amount_cents: int
    concentration_capped: bool
    effective_advance_rate: float
    eligible_collateral_value_cents: int
    required_paydown_cents: int
    outstanding_balance_cents: int
    dwell_days: int
    is_aged: bool
    rejected_reason: Optional[str]
    funded_at: Optional[str]
    wet_receipt_deadline_at: Optional[str]
    shipped_at: Optional[str]
    purchased_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WireInstruction(TypedDict):
    id: str
    advance_id: str
    payee_name: str
    payee_account_last4: str
    payee_routing_last4: str
    amount_cents: int
    status: str
    callback_reference: Optional[str]
    decided_by_user_id: Optional[str]
    block_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustodianReceipt(TypedDict):
    id: str
    advance_id: str
    custodian_id: str
    document_types: List[str]
    exception_codes: List[str]
    cured_exception_codes: List[str]
    status: str
    received_at: str
    created_at: str
    updated_at: str
    version: int


class BaileeLetter(TypedDict):
    id: str
    advance_id: str
    investor_id: str
    status: str
    effective_from: str
    bailee_period_days: int
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class MarginCall(TypedDict):
    id: str
    facility_id: str
    advance_id: Optional[str]
    trigger_reason: str
    call_amount_cents: int
    cured_amount_cents: int
    status: str
    issued_at: str
    cure_deadline_at: str
    issued_by_user_id: Optional[str]
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CovenantTest(TypedDict):
    id: str
    facility_id: str
    period_end: str
    tangible_net_worth_cents: int
    liquidity_cents: int
    net_income_cents: int
    profitability_variant: str
    profitability_metric_cents: int
    breach_codes: List[str]
    status: str
    certified_by_user_id: str
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepurchaseDemand(TypedDict):
    id: str
    advance_id: str
    reason: str
    demand_amount_cents: int
    status: str
    raised_at: str
    deadline_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only record: carries ONLY id and created_at as common fields.
class CurePayment(TypedDict):
    id: str
    margin_call_id: str
    amount_cents: int
    applied_to_fees_cents: int
    applied_to_principal_cents: int
    principal_allocation: List[dict]
    applied_at: str
    created_at: str


# Append-only record: carries ONLY id and created_at as common fields.
class LedgerEntry(TypedDict):
    id: str
    facility_id: str
    advance_id: Optional[str]
    entry_type: str
    direction: str
    amount_cents: int
    posted_at: str
    memo: str
    created_at: str
