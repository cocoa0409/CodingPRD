"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Shoe, Leather & Watch Repair PRD. Common-field entities carry
id + created_at + updated_at + version; the two append-only audit entities
(Payment, Notification) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status / enum value sets
# --------------------------------------------------------------------------
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class NotifyChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"


class ItemCategory(str, Enum):
    SHOE = "SHOE"
    LEATHER = "LEATHER"
    WATCH = "WATCH"


class Priority(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class RepairStatus(str, Enum):
    INTAKE = "INTAKE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    AWAITING_PARTS = "AWAITING_PARTS"
    IN_REPAIR = "IN_REPAIR"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    UNCLAIMED = "UNCLAIMED"
    DISPOSED = "DISPOSED"
    CANCELLED = "CANCELLED"


class NotifyStatus(str, Enum):
    NONE = "NONE"
    READY_NOTIFIED = "READY_NOTIFIED"
    UNCLAIMED_WARNED = "UNCLAIMED_WARNED"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class ServiceLineStatus(str, Enum):
    QUOTED = "QUOTED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PartsOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PaymentState(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    STORE_CREDIT = "STORE_CREDIT"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class NotificationKind(str, Enum):
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    UNCLAIMED_WARNING = "UNCLAIMED_WARNING"
    ESTIMATE_PRESENTED = "ESTIMATE_PRESENTED"


class UserRole(str, Enum):
    FRONT_DESK_CLERK = "FrontDeskClerk"
    REPAIR_TECHNICIAN = "RepairTechnician"
    SHOP_MANAGER = "ShopManager"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true → id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    notify_channel: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceType(TypedDict):
    id: str
    code: str
    name: str
    item_category: str
    base_price_cents: int
    standard_turnaround_days: int
    rush_eligible: bool
    warranty_days: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    display_name: str
    skills: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict):
    id: str
    customer_id: str
    drop_off_at: str
    priority: str
    repair_status: str
    notify_status: str
    ready_by: Optional[str]
    ready_at: Optional[str]
    sla_breached: Optional[bool]
    approved_estimate_id: Optional[str]
    final_charge_cents: Optional[int]
    amount_paid_cents: int
    warranty_expires_at: Optional[str]
    picked_up_at: Optional[str]
    assigned_technician_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TicketItem(TypedDict):
    id: str
    ticket_id: str
    item_category: str
    description: str
    condition_grade: str
    condition_notes: str
    created_at: str
    updated_at: str
    version: int


class ServiceLine(TypedDict):
    id: str
    ticket_id: str
    ticket_item_id: str
    service_type_id: str
    quoted_price_cents: int
    adjusted_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    ticket_id: str
    supersedes_estimate_id: Optional[str]
    revision_number: int
    authored_by_technician_id: str
    labor_subtotal_cents: int
    parts_subtotal_cents: int
    rush_surcharge_cents: int
    estimate_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsOrder(TypedDict):
    id: str
    ticket_id: str
    service_line_id: str
    part_name: str
    supplier_cost_cents: int
    quantity: int
    marked_up_cost_cents: int
    lead_time_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    ticket_id: str
    service_line_id: str
    reported_by_customer_id: str
    defect_description: str
    ruled_by_technician_id: Optional[str]
    status: str
    redo_ticket_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only audit entities (common_fields: false → only id + created_at)
# --------------------------------------------------------------------------
class Payment(TypedDict):
    id: str
    ticket_id: str
    amount_cents: int
    method: str
    state: str
    created_at: str


class Notification(TypedDict):
    id: str
    ticket_id: str
    kind: str
    channel: str
    body: str
    created_at: str
