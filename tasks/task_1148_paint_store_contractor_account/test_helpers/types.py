"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Tier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class JobStatus(str, Enum):
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    COMPLETE = "COMPLETE"


class CoatingCategory(str, Enum):
    FLAT = "FLAT"
    NON_FLAT = "NON_FLAT"
    INDUSTRIAL_MAINTENANCE = "INDUSTRIAL_MAINTENANCE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class FormulaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FormulaSource(str, Enum):
    LIBRARY = "LIBRARY"
    COLOR_MATCH = "COLOR_MATCH"


class MatchStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PROPOSED = "PROPOSED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    ABANDONED = "ABANDONED"


class BulletinStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EFFECTIVE = "EFFECTIVE"


class SpecStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVISION = "NEEDS_REVISION"
    SUPERSEDED = "SUPERSEDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class RebateStatus(str, Enum):
    ACCRUED = "ACCRUED"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class LoyaltyTxnType(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    CLAWBACK = "CLAWBACK"


class MistintStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    WRITTEN_OFF = "WRITTEN_OFF"


class UserRole(str, Enum):
    CORPORATE_ADMIN = "CorporateAdmin"
    STORE_MANAGER = "StoreManager"
    STORE_ASSOCIATE = "StoreAssociate"
    SPEC_WRITER = "SpecWriter"
    CONTRACTOR = "Contractor"


# --- Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version) ---


class ContractorAccount(TypedDict, total=False):
    id: str
    company_name: str
    status: str
    tier: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    loyalty_points_balance: int
    ytd_net_volume_cents: int
    lifetime_rebate_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class JobAccount(TypedDict, total=False):
    id: str
    contractor_account_id: str
    jurisdiction_id: str
    job_name: str
    site_address: str
    budget_cap_cents: Optional[int]
    status: str
    spent_cents: int
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    created_at: str
    updated_at: str
    version: int


class VocRule(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    category: str
    max_voc_gpl: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    voc_gpl: int
    list_price_cents: int
    tintable: bool
    status: str
    replacement_product_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TintFormula(TypedDict, total=False):
    id: str
    product_id: str
    color_code: str
    name: str
    shots: List[Dict[str, Any]]
    revision: int
    source: str
    status: str
    supersedes_formula_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ColorMatchRequest(TypedDict, total=False):
    id: str
    contractor_account_id: str
    product_id: str
    sample_reference: str
    status: str
    iteration_count: int
    formula_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductBulletin(TypedDict, total=False):
    id: str
    product_id: str
    replacement_product_id: str
    title: str
    effective_date: str
    status: str
    published_at: Optional[str]
    effected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecSheet(TypedDict, total=False):
    id: str
    project_code: str
    architect_name: str
    title: str
    status: str
    rejection_reason: Optional[str]
    approved_at: Optional[str]
    supersedes_spec_sheet_id: Optional[str]
    pull_through_ordered_pct: float
    pull_through_delivered_pct: float
    created_at: str
    updated_at: str
    version: int


class SpecLine(TypedDict, total=False):
    id: str
    spec_sheet_id: str
    product_id: str
    specified_qty: int
    obsoleted: bool
    ordered_qty: int
    delivered_qty: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    contractor_account_id: str
    job_account_id: str
    payment_status: str
    fulfillment_status: str
    tier_snapshot: str
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    refunded_cents: int
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    formula_id: Optional[str]
    spec_line_id: Optional[str]
    quantity: int
    returned_quantity: int
    unit_list_price_cents: int
    unit_price_cents: int
    line_total_cents: int
    is_custom_tint: bool
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entities (PRD §2.5): ONLY id + created_at; NO updated_at, NO version.
class ReturnRecord(TypedDict, total=False):
    id: str
    order_line_id: str
    quantity: int
    refund_merchandise_cents: int
    tax_refund_cents: int
    total_credit_cents: int
    created_at: str


class Delivery(TypedDict, total=False):
    id: str
    order_id: str
    job_account_id: str
    window_start: str
    window_end: str
    status: str
    failure_reason: Optional[str]
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RebateStatement(TypedDict, total=False):
    id: str
    contractor_account_id: str
    period_start: str
    period_end: str
    status: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    adjustment_cents: int
    payable_cents: Optional[int]
    period_net_cents: Optional[int]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entities (PRD §2.5): ONLY id + created_at; NO updated_at, NO version.
class LoyaltyTransaction(TypedDict, total=False):
    id: str
    contractor_account_id: str
    order_id: Optional[str]
    type: str
    points_delta: int
    note: str
    created_at: str


class MistintListing(TypedDict, total=False):
    id: str
    product_id: str
    formula_id: Optional[str]
    quantity: int
    cost_basis_cents: int
    list_price_cents: int
    current_price_cents: int
    status: str
    sold_price_cents: Optional[int]
    sold_to_contractor_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
