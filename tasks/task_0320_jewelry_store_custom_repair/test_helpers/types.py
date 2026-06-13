"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exact PRD field names. Payment and CreditLedgerEntry are
append-only (PRD §2.4): they expose only ``id`` and ``created_at`` and carry no
``updated_at`` / ``version``. All other resources carry the full common-field set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    SALES_ASSOCIATE = "SalesAssociate"
    GOLDSMITH = "Goldsmith"
    STORE_MANAGER = "StoreManager"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------- status enums
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InventoryItemStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    IN_REPAIR = "IN_REPAIR"


class WorkbenchStatus(str, Enum):
    ACTIVE = "ACTIVE"


class AppraisalStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class CustomDesignOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    IN_DESIGN = "IN_DESIGN"
    DESIGN_REVIEW = "DESIGN_REVIEW"
    APPROVED = "APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RepairTicketStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSED = "ASSESSED"
    AWAITING_PARTS = "AWAITING_PARTS"
    IN_REPAIR = "IN_REPAIR"
    QC = "QC"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class RepairKind(str, Enum):
    RESIZE = "RESIZE"
    STONE_RESET = "STONE_RESET"
    POLISH = "POLISH"
    CLASP_REPAIR = "CLASP_REPAIR"
    WARRANTY = "WARRANTY"


class LayawayPlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAID_IN_FULL = "PAID_IN_FULL"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class TradeInOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PLACED = "PLACED"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


class MetalKarat(str, Enum):
    K14 = "K14"
    K18 = "K18"
    K24 = "K24"


class TradeInCondition(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"


class PaymentTargetType(str, Enum):
    CUSTOM_ORDER = "CUSTOM_ORDER"
    LAYAWAY = "LAYAWAY"
    SPECIAL_ORDER = "SPECIAL_ORDER"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"


class LedgerDirection(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class LedgerReason(str, Enum):
    TRADE_IN = "TRADE_IN"
    LAYAWAY_REFUND = "LAYAWAY_REFUND"
    PURCHASE = "PURCHASE"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


# ------------------------------------------------------------------ entity typed dicts
# common_fields: true — carry id + created_at + updated_at + version
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    store_credit_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    sku: str
    title: str
    metal_karat: str
    list_price_cents: int
    latest_appraised_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Workbench(TypedDict):
    id: str
    label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    inventory_item_id: str
    appraiser_name: str
    appointment_start: str
    appointment_end: str
    market_value_cents: int
    replacement_factor: float
    replacement_value_cents: int
    document_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomDesignOrder(TypedDict):
    id: str
    customer_id: str
    description: str
    estimated_materials_cents: int
    design_fee_cents: int
    provisional_total_cents: int
    deposit_required_cents: int
    deposit_paid_cents: int
    final_total_cents: Optional[int]
    balance_due_cents: int
    line_items: List[dict]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict):
    id: str
    customer_id: str
    inventory_item_id: Optional[str]
    repair_kind: str
    parts_cents: int
    labor_cents: int
    rush: bool
    rush_surcharge_cents: int
    total_cents: int
    promised_at: str
    bench_id: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    warranty_claim_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LayawayPlan(TypedDict):
    id: str
    customer_id: str
    inventory_item_id: str
    item_price_cents: int
    down_payment_cents: int
    installment_count: int
    installment_amount_cents: int
    paid_to_date_cents: int
    projected_payoff_cents: int
    settlement_refund_cents: int
    restocking_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeInOffer(TypedDict):
    id: str
    customer_id: str
    metal_karat: str
    metal_weight_grams: float
    metal_spot_price_cents_per_gram: int
    gemstone_value_cents: int
    condition: str
    metal_value_cents: int
    buyback_credit_cents: int
    credit_ledger_entry_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    vendor_name: str
    catalog_ref: str
    quoted_price_cents: int
    deposit_required_cents: int
    deposit_paid_cents: int
    received_inventory_item_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    inventory_item_id: str
    customer_id: str
    defect_description: str
    spawned_repair_ticket_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carry ONLY id + created_at
class Payment(TypedDict):
    id: str
    target_type: str
    custom_order_id: Optional[str]
    layaway_plan_id: Optional[str]
    special_order_id: Optional[str]
    amount_cents: int
    outcome: str
    created_at: str


class CreditLedgerEntry(TypedDict):
    id: str
    customer_id: str
    direction: str
    amount_cents: int
    reason: str
    created_at: str
