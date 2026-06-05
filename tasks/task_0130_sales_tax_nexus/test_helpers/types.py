"""Domain types: entity TypedDicts, status enums, and the role enum.

All names follow the Sales Tax Nexus PRD terminology.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Status / enum value sets ─────────────────────────────────────────────

class SourcingRule(str, Enum):
    ORIGIN = "ORIGIN"
    DESTINATION = "DESTINATION"


class Taxability(str, Enum):
    FULL = "FULL"
    REDUCED = "REDUCED"
    EXEMPT = "EXEMPT"


class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NexusStatus(str, Enum):
    NO_NEXUS = "NO_NEXUS"
    THRESHOLD_MET = "THRESHOLD_MET"
    REGISTERED = "REGISTERED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class AuditStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"


class LineTaxability(str, Enum):
    FULL = "FULL"
    REDUCED = "REDUCED"
    EXEMPT = "EXEMPT"


class UseTaxAccrualStatus(str, Enum):
    ACCRUED = "ACCRUED"
    INCLUDED_IN_RETURN = "INCLUDED_IN_RETURN"


class TaxReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FILED = "FILED"
    REMITTED = "REMITTED"


class RemittancePaymentStatus(str, Enum):
    APPLIED = "APPLIED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SELLER = "Seller"
    TAX_PREPARER = "TaxPreparer"
    TAX_APPROVER = "TaxApprover"
    AUDITOR = "Auditor"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Full-resource entities carry id + created_at + updated_at + version.
# Append-only / line entities carry only id + created_at.

class TaxJurisdiction(TypedDict):
    id: str
    state_code: str
    sourcing_rule: str
    state_rate: float
    local_rate: float
    reduced_rate: float
    economic_nexus_sales_threshold: float
    economic_nexus_txn_threshold: int
    combined_rate: float
    created_at: str
    updated_at: str
    version: int


class ProductCategory(TypedDict):
    id: str
    jurisdiction_id: str
    category_code: str
    taxability: str
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict):
    id: str
    legal_name: str
    origin_state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NexusProfile(TypedDict):
    id: str
    seller_id: str
    jurisdiction_id: str
    cumulative_taxable_sales: float
    cumulative_txn_count: int
    nexus_status: str
    registered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExemptionCertificate(TypedDict):
    id: str
    seller_id: str
    jurisdiction_id: str
    customer_ref: str
    exempt_category_code: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketplaceFacilitator(TypedDict):
    id: str
    name: str
    collecting_state_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    seller_id: str
    jurisdiction_id: str
    facilitator_id: Optional[str]
    customer_ref: str
    customer_exempt_requested: bool
    sourcing_used: Optional[str]
    applied_rate: Optional[float]
    taxable_subtotal: float
    tax_collected: float
    remittance_responsibility: Optional[str]
    settlement_status: str
    audit_status: str
    tax_return_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only / fixed: carries ONLY id + created_at (no updated_at, no version).
class TransactionLineItem(TypedDict):
    id: str
    transaction_id: str
    category_code: str
    quantity: int
    unit_price: float
    line_taxability: Optional[str]
    line_tax: float
    created_at: str


class UseTaxAccrual(TypedDict):
    id: str
    seller_id: str
    jurisdiction_id: str
    purchase_amount: float
    accrued_use_tax: float
    status: str
    tax_return_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict):
    id: str
    seller_id: str
    jurisdiction_id: str
    period_start: str
    period_end: str
    prepared_by: str
    approved_by: Optional[str]
    tax_due: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RemittancePayment(TypedDict):
    id: str
    tax_return_id: str
    amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit entry: carries ONLY id + created_at.
class AuditLogEntry(TypedDict):
    id: str
    seller_id: str
    subject_entity: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    created_at: str
