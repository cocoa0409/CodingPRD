"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RETAILER = "Retailer"
    PRO = "Pro"
    CUSTOMER = "Customer"


class Category(str, Enum):
    TV_MOUNT = "TV_MOUNT"
    APPLIANCE = "APPLIANCE"
    SMART_DEVICE = "SMART_DEVICE"


class RetailerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProApplicationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REDO_REQUESTED = "REDO_REQUESTED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    HELD = "HELD"
    RELEASED = "RELEASED"
    REVERSED = "REVERSED"


class SettlementEntryStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class SettlementEntryType(str, Enum):
    CHARGE = "CHARGE"
    REVERSAL = "REVERSAL"


# --- Entity TypedDicts ---
# common_fields: true entities carry id + created_at + updated_at + version.

class Retailer(TypedDict):
    id: str
    name: str
    status: str
    commission_rate_bps: int
    settlement_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceZone(TypedDict):
    id: str
    zone_code: str
    name: str
    max_concurrent_appointments: int
    coverage_active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    address_line: str
    created_at: str
    updated_at: str
    version: int


class Pro(TypedDict):
    id: str
    full_name: str
    email: str
    service_zone_id: str
    skills: List[str]
    pending_payout_cents: int
    reserved_slot_count: int
    rating_sum: int
    rating_count: int
    rating_avg: float
    created_at: str
    updated_at: str
    version: int


class ProApplication(TypedDict):
    id: str
    pro_id: str
    status: str
    background_check_ref: str
    approved_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallTask(TypedDict):
    id: str
    task_code: str
    name: str
    category: str
    required_skill: str
    base_price_cents: int
    estimated_minutes: int
    warranty_days: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    addon_code: str
    name: str
    category: str
    price_cents: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    retailer_id: str
    customer_id: str
    install_task_id: str
    service_zone_id: str
    appointment_pro_id: Optional[str]
    product_sku: str
    product_category: str
    scope_notes: Optional[str]
    selected_addon_ids: List[str]
    status: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    quoted_price_cents: int
    final_price_cents: int
    completed_at: Optional[str]
    warranty_expires_at: Optional[str]
    redo_count: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    work_order_id: str
    pro_id: str
    status: str
    appointment_start: Optional[str]
    appointment_end: Optional[str]
    offered_at: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    work_order_id: str
    name: str
    unit_cost_cents: int
    quantity: int
    markup_bps: int
    line_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class PayoutRecord(TypedDict):
    id: str
    work_order_id: str
    pro_id: str
    retailer_id: str
    gross_task_cents: int
    commission_cents: int
    parts_reimbursement_cents: int
    payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailerSettlementEntry(TypedDict):
    id: str
    retailer_id: str
    work_order_id: str
    payout_record_id: str
    entry_type: str
    amount_cents: int
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — Rating is append-only: id + created_at ONLY (no updated_at, no version).
class Rating(TypedDict):
    id: str
    work_order_id: str
    pro_id: str
    customer_id: str
    stars: int
    comment: Optional[str]
    created_at: str
