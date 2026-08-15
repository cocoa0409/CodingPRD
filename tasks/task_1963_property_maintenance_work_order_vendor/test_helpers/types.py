"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the standard system-managed fields (id, created_at,
updated_at, version) described in PRD section "Common Resource Properties".
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    RESIDENT = "Resident"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    VENDOR = "Vendor"
    PROPERTY_MANAGER = "PropertyManager"


class Trade(str, Enum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    APPLIANCE = "APPLIANCE"
    GENERAL = "GENERAL"


class Priority(str, Enum):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class WorkOrderStatus(str, Enum):
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AssignmentType(str, Enum):
    IN_HOUSE = "IN_HOUSE"
    VENDOR = "VENDOR"


class EntryAuthorization(str, Enum):
    EMERGENCY_ACCESS = "EMERGENCY_ACCESS"
    RESIDENT_CONSENT = "RESIDENT_CONSENT"
    NOTICE_POSTED = "NOTICE_POSTED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RestockStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"


class WorkOrderPartStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class PurchaseRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    RECEIVED = "RECEIVED"


class ChargebackStatus(str, Enum):
    PENDING = "PENDING"
    BILLED = "BILLED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class Property(TypedDict, total=False):
    id: str
    name: str
    emergency_response_hours: int
    emergency_completion_hours: int
    urgent_response_hours: int
    urgent_completion_hours: int
    routine_response_hours: int
    routine_completion_hours: int
    purchase_auto_approve_threshold_cents: int
    recall_window_days: int
    vendor_travel_buffer_minutes: int
    entry_notice_min_hours: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    property_id: str
    unit_number: str
    full_name: str
    email: str
    chargeback_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    property_id: str
    full_name: str
    trade: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    property_id: str
    company_name: str
    trade: str
    insurance_valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    property_id: str
    sku: str
    name: str
    unit_cost_cents: int
    reorder_level: int
    initial_stock: int
    quantity_on_hand: int
    reserved_quantity: int
    restock_status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    property_id: str
    resident_id: str
    unit_number: str
    category: str
    priority: str
    description: str
    status: str
    assignment_type: Optional[str]
    assigned_technician_id: Optional[str]
    assigned_vendor_id: Optional[str]
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    entry_authorization: Optional[str]
    notice_posted_at: Optional[str]
    first_responded_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    closed_at: Optional[str]
    response_due_at: str
    completion_due_at: str
    response_sla_breached: bool
    completion_sla_breached: bool
    resident_signoff: bool
    photo_urls: List[str]
    damage_reported: bool
    estimated_damage_cost_cents: Optional[int]
    recall_count: int
    parts_total_cents: int
    created_at: str
    updated_at: str
    version: int


class WorkOrderPart(TypedDict, total=False):
    id: str
    work_order_id: str
    part_id: str
    quantity: int
    unit_cost_cents_snapshot: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseRequest(TypedDict, total=False):
    id: str
    work_order_id: str
    part_id: str
    quantity: int
    quoted_unit_cost_cents: int
    shipping_fee_cents: int
    items_subtotal_cents: int
    handling_fee_cents: int
    estimated_total_cents: int
    auto_approved: bool
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargebackLine(TypedDict, total=False):
    description: str
    quantity: int
    unit_cost_cents: int
    resident_share_pct: float


class Chargeback(TypedDict, total=False):
    id: str
    work_order_id: str
    resident_id: str
    provisional_amount_cents: int
    line_items: List[ChargebackLine]
    final_amount_cents: Optional[int]
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
