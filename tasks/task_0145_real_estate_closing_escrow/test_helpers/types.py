"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: most resources carry id, created_at, updated_at, version.
CCRDisclosure and AuditEvent are exceptions — they carry only id and
created_at (no updated_at, no version).
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    EscrowOfficer = "EscrowOfficer"
    TitleOfficer = "TitleOfficer"
    DisbursementApprover = "DisbursementApprover"
    Buyer = "Buyer"
    Seller = "Seller"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class EscrowFileStatus(str, Enum):
    OPEN = "OPEN"
    CONTINGENT_TITLE = "CONTINGENT_TITLE"
    CONTINGENT_CD = "CONTINGENT_CD"
    CONTINGENT_WIRE = "CONTINGENT_WIRE"
    READY_TO_CLOSE = "READY_TO_CLOSE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EMDStatus(str, Enum):
    PENDING_FUNDS = "PENDING_FUNDS"
    HELD = "HELD"
    RELEASED_TO_SELLER = "RELEASED_TO_SELLER"
    RELEASED_TO_BUYER = "RELEASED_TO_BUYER"
    SPLIT = "SPLIT"


class TitleSearchStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    CLEARED = "CLEARED"
    DEFECTIVE = "DEFECTIVE"


class TitlePolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    VOIDED = "VOIDED"


class PolicyKind(str, Enum):
    OWNERS = "OWNERS"
    LENDERS = "LENDERS"


class CDStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    READY_TO_FUND = "READY_TO_FUND"
    REVISED = "REVISED"
    VOIDED = "VOIDED"


class CDTriggeringChangeKind(str, Enum):
    NONE = "NONE"
    APR_DELTA_OVER_THRESHOLD = "APR_DELTA_OVER_THRESHOLD"
    LOAN_PRODUCT_CHANGE = "LOAN_PRODUCT_CHANGE"
    PREPAYMENT_PENALTY_ADDED = "PREPAYMENT_PENALTY_ADDED"
    FEE_DELTA_UNDER_THRESHOLD = "FEE_DELTA_UNDER_THRESHOLD"


class WireStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"
    REJECTED_FRAUD_FLAG = "REJECTED_FRAUD_FLAG"


class BeneficiaryKind(str, Enum):
    SELLER = "SELLER"
    LENDER_PAYOFF = "LENDER_PAYOFF"
    QUALIFIED_INTERMEDIARY = "QUALIFIED_INTERMEDIARY"
    TAX_AUTHORITY = "TAX_AUTHORITY"


class CallbackChannel(str, Enum):
    VOICE_VERIFIED = "VOICE_VERIFIED"
    IN_PERSON_VERIFIED = "IN_PERSON_VERIFIED"


class DisbursementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SENT = "SENT"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ExchangeStatus(str, Enum):
    INITIATED = "INITIATED"
    IDENTIFIED = "IDENTIFIED"
    CLOSED_DEFERRED = "CLOSED_DEFERRED"
    FAILED_TAXABLE = "FAILED_TAXABLE"


class PartyKind(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    LENDER = "LENDER"
    QUALIFIED_INTERMEDIARY = "QUALIFIED_INTERMEDIARY"


class CancelReason(str, Enum):
    BUYER_DEFAULT = "BUYER_DEFAULT"
    SELLER_DEFAULT = "SELLER_DEFAULT"
    TITLE_DEFECT = "TITLE_DEFECT"
    MUTUAL_RELEASE = "MUTUAL_RELEASE"


class AuditSubjectKind(str, Enum):
    EMD = "EMD"
    TITLE_SEARCH = "TITLE_SEARCH"
    TITLE_POLICY = "TITLE_POLICY"
    CCR = "CCR"
    CD = "CD"
    WIRE = "WIRE"
    DISBURSEMENT = "DISBURSEMENT"
    EXCHANGE_1031 = "EXCHANGE_1031"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields:true → id, created_at, updated_at, version.
# CCRDisclosure and AuditEvent (common_fields:false) carry only id + created_at.
# ---------------------------------------------------------------------------
class Party(TypedDict, total=False):
    id: str
    full_name: str
    party_kind: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    street_address: str
    parcel_id: str
    hoa_annual_dues: float
    tax_annual: float
    created_at: str
    updated_at: str
    version: int


class EscrowFile(TypedDict, total=False):
    id: str
    property_id: str
    buyer_party_id: str
    seller_party_id: str
    lender_party_id: Optional[str]
    qi_party_id: Optional[str]
    purchase_price: float
    loan_amount: float
    closing_date_planned: str
    status: str
    is_1031_exchange: bool
    created_at: str
    updated_at: str
    version: int


class EarnestMoneyDeposit(TypedDict, total=False):
    id: str
    escrow_file_id: str
    amount: float
    forfeited_amount: float
    refunded_amount: float
    status: str
    split_buyer_share: float
    split_seller_share: float
    created_at: str
    updated_at: str
    version: int


class TitleSearch(TypedDict, total=False):
    id: str
    escrow_file_id: str
    chain_of_title_clean: bool
    open_liens_total: float
    encumbrance_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleInsurancePolicy(TypedDict, total=False):
    id: str
    escrow_file_id: str
    policy_kind: str
    insured_amount: float
    simultaneous_issue: bool
    premium: float
    status: str
    created_at: str
    updated_at: str
    version: int


# CCRDisclosure is immutable — PRD §2.4 / §3.4: no updated_at, no version.
class CCRDisclosure(TypedDict, total=False):
    id: str
    escrow_file_id: str
    ccr_document_hash: str
    buyer_acknowledged_at: str
    material_restrictions: List[str]
    created_at: str


class ClosingDisclosure(TypedDict, total=False):
    id: str
    escrow_file_id: str
    version_number: int
    cash_to_close: float
    total_loan_costs: float
    seller_credits: float
    prorated_tax_credit: float
    prorated_hoa_credit: float
    seller_days_owned: int
    issued_at: Optional[str]
    earliest_funding_at: Optional[str]
    buyer_acknowledged_at: Optional[str]
    status: str
    triggering_change_kind: str
    created_at: str
    updated_at: str
    version: int


class WireInstruction(TypedDict, total=False):
    id: str
    escrow_file_id: str
    beneficiary_kind: str
    beneficiary_party_id: str
    routing_number: str
    account_number_last4: str
    confirmation_callback_at: Optional[str]
    confirmed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    escrow_file_id: str
    wire_instruction_id: str
    amount: float
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Exchange1031(TypedDict, total=False):
    id: str
    escrow_file_id: str
    relinquished_basis: float
    relinquished_sale_price: float
    cash_boot_received: float
    mortgage_relief: float
    realized_gain: float
    recognized_gain: float
    deferred_gain: float
    identification_deadline_at: str
    exchange_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# AuditEvent is append-only — PRD §2.4: no updated_at, no version.
class AuditEvent(TypedDict, total=False):
    id: str
    escrow_file_id: str
    subject_kind: str
    subject_id: str
    actor_user_id: str
    actor_role: str
    action: str
    payload_hash: str
    created_at: str


class ServerClock(TypedDict, total=False):
    now: str


__all__ = [
    "UserRole",
    "EscrowFileStatus",
    "EMDStatus",
    "TitleSearchStatus",
    "TitlePolicyStatus",
    "PolicyKind",
    "CDStatus",
    "CDTriggeringChangeKind",
    "WireStatus",
    "BeneficiaryKind",
    "CallbackChannel",
    "DisbursementStatus",
    "ExchangeStatus",
    "PartyKind",
    "CancelReason",
    "AuditSubjectKind",
    "Party",
    "Property",
    "EscrowFile",
    "EarnestMoneyDeposit",
    "TitleSearch",
    "TitleInsurancePolicy",
    "CCRDisclosure",
    "ClosingDisclosure",
    "WireInstruction",
    "Disbursement",
    "Exchange1031",
    "AuditEvent",
    "ServerClock",
]
