"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DESIGNER = "Designer"
    SHOP_ADMIN = "ShopAdmin"


class PaperStockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class FinishOptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class EventPackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class EventPackageType(str, Enum):
    WEDDING = "WEDDING"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    CUSTOM = "CUSTOM"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    PROOFING = "PROOFING"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"


class ProofStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    CART = "CART"
    DEPOSIT_PENDING = "DEPOSIT_PENDING"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AddressingJobType(str, Enum):
    ADDRESSING = "ADDRESSING"
    ASSEMBLY = "ASSEMBLY"


class AddressingJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkOrderProductionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PRINTING = "PRINTING"
    FINISHING = "FINISHING"
    COMPLETED = "COMPLETED"


class WorkOrderAddressingStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ShipmentStatus(str, Enum):
    PREPARING = "PREPARING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    credit_balance_cents: int
    cumulative_deposits_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Designer(TypedDict):
    id: str
    full_name: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class PaperStock(TypedDict):
    id: str
    name: str
    base_price_cents: int
    lead_days: int
    status: str
    reserved_units: int
    created_at: str
    updated_at: str
    version: int


class FinishOption(TypedDict):
    id: str
    name: str
    surcharge_cents: int
    additional_lead_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventPackage(TypedDict):
    id: str
    name: str
    package_type: str
    deposit_pct: float
    min_qty: int
    proof_expiry_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Design(TypedDict):
    id: str
    customer_id: str
    designer_id: Optional[str]
    event_package_id: str
    paper_stock_id: str
    finish_option_id: str
    notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict):
    id: str
    design_id: str
    designer_id: str
    current_revision_number: int
    revision_fee_cents: int
    submitted_at: Optional[str]
    expires_at: Optional[str]
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    design_id: str
    proof_id: Optional[str]
    event_package_id: str
    prior_order_id: Optional[str]
    rush_requested: bool
    rush_deadline: Optional[str]
    subtotal_cents: int
    reorder_discount_cents: int
    rush_surcharge_cents: int
    total_cents: int
    deposit_due_cents: int
    deposit_paid_cents: int
    deposit_paid_at: Optional[str]
    balance_due_cents: int
    expected_lead_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict):
    id: str
    order_id: str
    paper_stock_id: str
    finish_option_id: str
    quantity: int
    captured_base_price_cents: int
    captured_finish_surcharge_cents: int
    line_price_cents: int
    created_at: str
    updated_at: str
    version: int


class AddressingJob(TypedDict):
    id: str
    order_id: str
    job_type: str
    quantity: int
    scheduled_date: str
    unit_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    order_id: str
    press_id: Optional[str]
    press_slot_start: Optional[str]
    press_slot_end: Optional[str]
    production_status: str
    addressing_status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    tracking_number: str
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
