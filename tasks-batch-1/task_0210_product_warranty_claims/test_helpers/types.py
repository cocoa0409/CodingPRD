"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3).

Per PRD §2.4, four entities carry the full common-field set (id, created_at,
updated_at, version): Product, CoverageTier, Registration, ExtendedWarranty,
ProofOfPurchase, Claim. Three are deliberately leaner — Owner, WarrantyTransfer,
and LedgerEntry carry ONLY id and created_at (no updated_at, no version).
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────
class UserRole(str, Enum):
    OWNER = "Owner"
    WARRANTY_ADMIN = "WarrantyAdmin"
    CLAIMS_PROCESSOR = "ClaimsProcessor"


# ─── Status enums (PRD §3) ───────────────────────────────────────────────────
class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductCategory(str, Enum):
    ELECTRONICS = "ELECTRONICS"
    APPLIANCE = "APPLIANCE"
    POWER_TOOL = "POWER_TOOL"
    FURNITURE = "FURNITURE"


class TierName(str, Enum):
    BASE = "BASE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class DepreciationMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    DECLINING_BALANCE = "DECLINING_BALANCE"


class PremiumRefundMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    SHORT_RATE = "SHORT_RATE"


class CoverageTierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProofStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ProofDocumentType(str, Enum):
    RECEIPT = "RECEIPT"
    INVOICE = "INVOICE"
    BANK_STATEMENT = "BANK_STATEMENT"


class ProofState(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    DATE_MISMATCH = "DATE_MISMATCH"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    EXPIRED_WINDOW = "EXPIRED_WINDOW"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class ExtendedWarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class DefectCategory(str, Enum):
    MANUFACTURING = "MANUFACTURING"
    WEAR_AND_TEAR = "WEAR_AND_TEAR"
    ACCIDENTAL = "ACCIDENTAL"
    COSMETIC = "COSMETIC"


class ResolutionType(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"
    REFUND = "REFUND"


class ClaimStatus(str, Enum):
    INTAKE = "INTAKE"
    RMA_ISSUED = "RMA_ISSUED"
    ADJUDICATED = "ADJUDICATED"
    FULFILLED = "FULFILLED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class TransferStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"


class LedgerEntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerReason(str, Enum):
    REPAIR_COST = "REPAIR_COST"
    REPLACE_COST = "REPLACE_COST"
    REFUND_PAYOUT = "REFUND_PAYOUT"
    REVERSAL = "REVERSAL"
    TRANSFER_FEE = "TRANSFER_FEE"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# common_fields: true — carries id + created_at + updated_at + version.
class Product(TypedDict):
    id: str
    model_number: str
    category: str
    msrp_cents: int
    base_warranty_months: int
    serviceable_lifespan_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only/identity; carries ONLY id + created_at.
class Owner(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str


class CoverageTier(TypedDict):
    id: str
    product_id: str
    tier_name: str
    extension_months: int
    price_cents: int
    coverage_cap_cents: int
    depreciation_method: str
    refund_eligible: bool
    premium_refund_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    product_id: str
    serial_number: str
    owner_user_id: str
    purchase_date: str
    purchase_price_cents: int
    proof_status: str
    warranty_end_date: str
    remaining_coverage_cents: int
    status: str
    active_tier_id: str
    created_at: str
    updated_at: str
    version: int


class ExtendedWarranty(TypedDict):
    id: str
    registration_id: str
    coverage_tier_id: str
    amount_paid_cents: int
    effective_date: str
    premium_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProofOfPurchase(TypedDict):
    id: str
    registration_id: str
    document_type: str
    stated_purchase_date: str
    stated_amount_cents: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    registration_id: str
    defect_category: str
    reported_date: str
    resolution_type: Optional[str]
    rma_number: Optional[str]
    assessed_value_cents: int
    claims_processor_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event; ONLY id + created_at.
class WarrantyTransfer(TypedDict):
    id: str
    registration_id: str
    from_owner_user_id: str
    to_owner_user_id: str
    transfer_fee_cents: int
    status: str
    created_at: str


# common_fields: false — append-only ledger row; ONLY id + created_at.
class LedgerEntry(TypedDict):
    id: str
    registration_id: str
    claim_id: Optional[str]
    entry_type: str
    reason: str
    amount_cents: int
    created_at: str
