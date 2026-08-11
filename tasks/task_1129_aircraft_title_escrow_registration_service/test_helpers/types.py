"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ESCROW_OFFICER = "EscrowOfficer"
    ESCROW_MANAGER = "EscrowManager"
    LENDER_REP = "LenderRep"
    AUDITOR = "Auditor"


class AircraftRegistryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    DEREGISTRATION_PENDING = "DEREGISTRATION_PENDING"
    DEREGISTERED = "DEREGISTERED"
    EXPORTED = "EXPORTED"


class PartyType(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    LENDER = "LENDER"
    TRUSTEE = "TRUSTEE"


class EscrowFileStatus(str, Enum):
    OPENED = "OPENED"
    SEARCH_ORDERED = "SEARCH_ORDERED"
    SEARCH_COMPLETE = "SEARCH_COMPLETE"
    CLEARED = "CLEARED"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class EscrowPosture(str, Enum):
    READY = "READY"
    LIEN_BLOCKED = "LIEN_BLOCKED"
    TRUST_BLOCKED = "TRUST_BLOCKED"
    LIEN_AND_TRUST_BLOCKED = "LIEN_AND_TRUST_BLOCKED"


class ProrationMethod(str, Enum):
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


class TrustAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class BeneficiaryCitizenship(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    NON_US_CITIZEN = "NON_US_CITIZEN"


class TitleSearchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    STALE = "STALE"


class LienType(str, Enum):
    FAA_RECORDED = "FAA_RECORDED"
    IR_INTEREST = "IR_INTEREST"
    STATE = "STATE"
    JUDGMENT = "JUDGMENT"


class LienStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    DISPUTED = "DISPUTED"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"


class LienReleaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    RELEASE_RECEIVED = "RELEASE_RECEIVED"
    FILED = "FILED"
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"
    QUOTE_EXPIRED = "QUOTE_EXPIRED"


class PayoffBasis(str, Enum):
    FLAT = "FLAT"
    PER_DIEM = "PER_DIEM"


class DepositStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RETURNED = "RETURNED"


class DepositPurpose(str, Enum):
    EARNEST_MONEY = "EARNEST_MONEY"
    BUYER_FUNDS = "BUYER_FUNDS"
    LENDER_FUNDS = "LENDER_FUNDS"


class DisbursementStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class DisbursementPurpose(str, Enum):
    LIEN_PAYOFF = "LIEN_PAYOFF"
    SELLER_PROCEEDS = "SELLER_PROCEEDS"
    ESCROW_FEE = "ESCROW_FEE"
    TAX_REMITTANCE = "TAX_REMITTANCE"
    OTHER = "OTHER"


class FilingType(str, Enum):
    BILL_OF_SALE = "BILL_OF_SALE"
    REGISTRATION_APPLICATION = "REGISTRATION_APPLICATION"
    MORTGAGE_RECORDATION = "MORTGAGE_RECORDATION"
    DEREGISTRATION = "DEREGISTRATION"
    EXPORT_CERTIFICATE = "EXPORT_CERTIFICATE"


class FilingStatus(str, Enum):
    QUEUED = "QUEUED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class VerificationStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"


class DocType(str, Enum):
    PURCHASE_AGREEMENT = "PURCHASE_AGREEMENT"
    ESCROW_INSTRUCTIONS = "ESCROW_INSTRUCTIONS"
    BILL_OF_SALE_DOC = "BILL_OF_SALE_DOC"
    WIRE_AUTHORIZATION = "WIRE_AUTHORIZATION"
    CLOSING_STATEMENT = "CLOSING_STATEMENT"


class DocumentStatus(str, Enum):
    PREPARED = "PREPARED"
    OUT_FOR_SIGNATURE = "OUT_FOR_SIGNATURE"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    FULLY_SIGNED = "FULLY_SIGNED"


# All resources carry the PRD §2.5 standard system-managed field set
# (id, created_at, updated_at, version), so every TypedDict includes them.


class Aircraft(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    n_number: str
    serial_number: str
    make_model: str
    year: int
    is_international_registry: bool
    registry_status: str


class Party(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    party_type: str
    legal_name: str
    email: Optional[str]
    is_citizenship_verified: bool


class EscrowFile(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    aircraft_id: str
    buyer_party_id: str
    seller_party_id: str
    lender_party_id: Optional[str]
    trustee_party_id: Optional[str]
    requires_trust: bool
    purchase_price_cents: int
    annual_registration_fee_cents: int
    proration_method: str
    expected_close_date: str
    status: str
    posture: str
    hold_return_state: Optional[str]
    escrow_fee_cents: int
    proration_amount_cents: int
    buyer_amount_due_cents: int
    total_funded_cents: int
    escrow_balance_cents: int
    seller_net_proceeds_cents: int
    closed_at: Optional[str]


class TrustAgreement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    aircraft_id: str
    trustee_party_id: str
    beneficiary_name: str
    beneficiary_citizenship: str
    effective_date: str
    expiry_date: str
    status: str
    submitted_at: Optional[str]


class TitleSearch(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    escrow_file_id: str
    status: str
    effective_at: Optional[str]
    completed_at: Optional[str]
    finding_count: int


class Lien(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    escrow_file_id: str
    aircraft_id: str
    title_search_id: str
    lienor_party_id: str
    lienor_name: str
    original_amount_cents: int
    amount_paid_cents: int
    outstanding_cents: int
    lien_type: str
    filed_at: str
    ir_registered_at: Optional[str]
    priority_rank: int
    status: str


class LienRelease(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    lien_id: str
    status: str
    payoff_basis: Optional[str]
    quoted_payoff_cents: Optional[int]
    per_diem_cents: Optional[int]
    quote_date: Optional[str]
    good_through_date: Optional[str]


class Deposit(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    escrow_file_id: str
    payer_party_id: str
    amount_cents: int
    purpose: str
    status: str
    returned_at: Optional[str]


class DisbursementInstruction(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    escrow_file_id: str
    payee_party_id: str
    lien_id: Optional[str]
    amount_cents: int
    purpose: str
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]


class Filing(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    escrow_file_id: str
    aircraft_id: str
    filing_type: str
    status: str
    verification_status: str
    registry_confirmation_code: Optional[str]
    reject_reason: Optional[str]
    submitted_at: Optional[str]
    sequence_index: Optional[int]


class ClosingDocument(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    escrow_file_id: str
    doc_type: str
    required_signer_party_ids: List[str]
    signed_party_ids: List[str]
    status: str


class ClosingStatement(TypedDict, total=False):
    purchase_price_cents: int
    proration_amount_cents: int
    escrow_fee_cents: int
    buyer_amount_due_cents: int
    total_funded_cents: int
    escrow_balance_cents: int
    seller_net_proceeds_cents: int
