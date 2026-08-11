"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT_OPS = "ClientOps"
    WAREHOUSE_OPS = "WarehouseOps"
    BILLING_ADMIN = "BillingAdmin"
    CUSTOMER_SERVICE = "CustomerService"


class BoxPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class KitRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class ImportBatchStatus(str, Enum):
    UPLOADED = "UPLOADED"
    COMMITTED = "COMMITTED"


class SubscriberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CHURNED = "CHURNED"


class ChurnReason(str, Enum):
    PRICE = "PRICE"
    PRODUCT = "PRODUCT"
    MOVED = "MOVED"
    OTHER = "OTHER"


class AssemblyRunStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    KITTING = "KITTING"
    KITTED = "KITTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FulfillStatus(str, Enum):
    QUEUED = "QUEUED"
    STAGED = "STAGED"
    ASSIGNED = "ASSIGNED"
    MANIFESTED = "MANIFESTED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class LabelStatus(str, Enum):
    NONE = "NONE"
    PURCHASED = "PURCHASED"
    VOIDED = "VOIDED"


class Carrier(str, Enum):
    USPS = "USPS"
    UPS = "UPS"
    FEDEX = "FEDEX"


class ServiceLevel(str, Enum):
    GROUND = "GROUND"
    EXPRESS = "EXPRESS"


class ShippingWaveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MANIFESTED = "MANIFESTED"
    TENDERED = "TENDERED"
    CANCELLED = "CANCELLED"


class ReturnReason(str, Enum):
    DAMAGED = "DAMAGED"
    LOST = "LOST"
    WRONG_ITEM = "WRONG_ITEM"
    OTHER = "OTHER"


class RequestedResolution(str, Enum):
    REPLACE = "REPLACE"
    REFUND = "REFUND"


class ReturnCaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    RESOLVED = "RESOLVED"


class ResolutionApplied(str, Enum):
    REPLACED = "REPLACED"
    REFUNDED = "REFUNDED"


class BillingStatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class InventoryEventType(str, Enum):
    RECEIPT = "RECEIPT"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    COMMIT = "COMMIT"


class StockStatus(str, Enum):
    OK = "OK"
    LOW = "LOW"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---


class Client(TypedDict, total=False):
    id: str
    name: str
    billing_email: str
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class BoxPlan(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    sku: str
    price_per_box_cents: int
    shipping_weight_grams: int
    status: str
    active_revision_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KitRevision(TypedDict, total=False):
    id: str
    plan_id: str
    revision_no: int
    supersedes_revision_id: Optional[str]
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# KitBOMLine is wholesale-replaced (common_fields: false): only id + created_at.
class KitBOMLine(TypedDict, total=False):
    id: str
    revision_id: str
    component_id: str
    qty_per_box: int
    created_at: str


class Component(TypedDict, total=False):
    id: str
    sku: str
    name: str
    unit_cost_cents: int
    reorder_point_units: int
    on_hand_units: int
    reserved_units: int
    available_units: int
    projected_available_units: int
    stock_status: str
    created_at: str
    updated_at: str
    version: int


# InventoryEvent is an append-only ledger entry (common_fields: false): only id + created_at.
class InventoryEvent(TypedDict, total=False):
    id: str
    component_id: str
    run_id: Optional[str]
    event_type: str
    quantity_delta: int
    note: Optional[str]
    created_at: str


class ImportBatch(TypedDict, total=False):
    id: str
    plan_id: str
    rows: list
    total_rows: int
    accepted_count: int
    rejected_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict, total=False):
    id: str
    plan_id: str
    import_batch_id: str
    email: str
    full_name: Optional[str]
    zone: int
    status: str
    churned_at: Optional[str]
    churn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssemblyRun(TypedDict, total=False):
    id: str
    plan_id: str
    period: str
    planned_box_count: int
    kitted_box_count: int
    estimate_cents: int
    status: str
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    run_id: str
    subscriber_id: str
    wave_id: Optional[str]
    fulfill_status: str
    label_status: str
    postage_cents: int
    tracking_code: Optional[str]
    is_replacement: bool
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShippingWave(TypedDict, total=False):
    id: str
    carrier: str
    service_level: str
    pickup_start: str
    pickup_end: str
    status: str
    assigned_count: int
    created_at: str
    updated_at: str
    version: int


class ReturnCase(TypedDict, total=False):
    id: str
    shipment_id: str
    reason: str
    requested_resolution: str
    status: str
    resolution_applied: Optional[str]
    credit_cents: int
    replacement_shipment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict, total=False):
    id: str
    client_id: str
    period: str
    box_charge_cents: int
    postage_cents: int
    refund_credit_cents: int
    discount_pct: int
    adjustment_credit_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
