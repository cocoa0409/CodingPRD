"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status Enums (PRD §3) ───────────────────────────────────────


class PurchaseAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLEARED_TO_CLOSE = "CLEARED_TO_CLOSE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class EscrowAccountStatus(str, Enum):
    OPEN = "OPEN"
    FUNDED = "FUNDED"
    DISBURSED = "DISBURSED"
    CLOSED = "CLOSED"


class EarnestMoneyDepositStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class TitleSearchStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    RESOLVED = "RESOLVED"


class TitleInsurancePolicyStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class ClosingDisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    DELIVERED = "DELIVERED"
    REISSUED = "REISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"


class CDProductType(str, Enum):
    FIXED = "FIXED"
    ARM = "ARM"
    IO = "IO"
    BALLOON = "BALLOON"


class WireInstructionStatus(str, Enum):
    PROVIDED = "PROVIDED"
    VERIFIED = "VERIFIED"
    LOCKED = "LOCKED"
    REJECTED = "REJECTED"


class WireParty(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    LENDER = "LENDER"
    EXCHANGE_ACCOMMODATOR = "EXCHANGE_ACCOMMODATOR"


class DisbursementStatus(str, Enum):
    QUEUED = "QUEUED"
    DISBURSED = "DISBURSED"
    REVERSED = "REVERSED"


class DisbursementPurpose(str, Enum):
    SELLER_PROCEEDS = "SELLER_PROCEEDS"
    LENDER_PAYOFF = "LENDER_PAYOFF"
    TITLE_PREMIUM = "TITLE_PREMIUM"
    EXCHANGE_FUNDS = "EXCHANGE_FUNDS"
    EARNEST_REFUND = "EARNEST_REFUND"


class DepositorRole(str, Enum):
    BUYER = "BUYER"
    BUYERS_AGENT = "BUYERS_AGENT"


class ExchangeAccountStatus(str, Enum):
    OPEN = "OPEN"
    IDENTIFIED = "IDENTIFIED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UserRole(str, Enum):
    ESCROW_OFFICER = "EscrowOfficer"
    TITLE_AGENT = "TitleAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class DefectSeverity(str, Enum):
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"


# ─── Entity TypedDicts (PRD §2.4) ───────────────────────────────
# Mutable entities carry id + created_at + updated_at + version.
# Append-only entities (CCRReview, User) carry only id + created_at.


class PurchaseAgreement(TypedDict, total=False):
    id: str
    buyer_name: str
    seller_name: str
    property_address: str
    purchase_price_cents: int
    earnest_money_required_cents: int
    scheduled_closing_date: str
    exchange_account_id: Optional[str]
    status: str
    earnest_money_received_cents: int
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict, total=False):
    id: str
    agreement_id: str
    escrow_officer_id: str
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EarnestMoneyDeposit(TypedDict, total=False):
    id: str
    escrow_account_id: str
    amount_cents: int
    depositor_role: str
    confirmation_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleSearch(TypedDict, total=False):
    id: str
    agreement_id: str
    defects: list
    status: str
    has_material_defect: bool
    created_at: str
    updated_at: str
    version: int


class TitleInsurancePolicy(TypedDict, total=False):
    id: str
    title_search_id: str
    coverage_amount_cents: int
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CCRReview(TypedDict, total=False):
    # Append-only (PRD §2.4) — no updated_at, no version.
    id: str
    agreement_id: str
    hoa_name: Optional[str]
    restrictions_summary: str
    buyer_acknowledged: bool
    created_at: str


class ClosingDisclosure(TypedDict, total=False):
    id: str
    agreement_id: str
    issued_at: Optional[str]
    cd_apr_bps: int
    cd_total_loan_amount_cents: int
    cd_monthly_payment_cents: int
    cd_product_type: str
    cd_prepayment_penalty: bool
    status: str
    earliest_consummation_at: Optional[str]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WireInstruction(TypedDict, total=False):
    id: str
    agreement_id: str
    party: str
    beneficiary_bank_name: str
    beneficiary_account_last4: str
    routing_number: str
    voice_callback_completed: bool
    callback_verified_at: Optional[str]
    callback_verifier_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    escrow_account_id: str
    wire_instruction_id: str
    purpose: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExchangeAccount(TypedDict, total=False):
    id: str
    taxpayer_name: str
    qualified_intermediary_name: str
    relinquished_closing_date: str
    identification_deadline: str
    exchange_deadline: str
    replacement_property_identified: bool
    identified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class User(TypedDict, total=False):
    # Append-only/immutable (PRD §2.4) — no updated_at, no version.
    id: str
    role: str
    full_name: str
    created_at: str
