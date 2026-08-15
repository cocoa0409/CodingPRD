"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TechnicianCapability(str, Enum):
    TECHNICIAN = "TECHNICIAN"
    SUPERVISOR = "SUPERVISOR"


class HabitabilityStatus(str, Enum):
    HABITABLE = "HABITABLE"
    UNINHABITABLE = "UNINHABITABLE"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VendorTrade(str, Enum):
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    ELECTRICAL = "ELECTRICAL"
    GENERAL = "GENERAL"
    RESTORATION = "RESTORATION"


class RotationShiftStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CallTicketStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    DISPATCHED = "DISPATCHED"
    ESCALATED = "ESCALATED"
    ON_SCENE = "ON_SCENE"
    MITIGATED = "MITIGATED"
    CLOSED = "CLOSED"
    DEFERRED = "DEFERRED"


class CallTicketCategory(str, Enum):
    GAS_LEAK = "GAS_LEAK"
    FLOOD = "FLOOD"
    NO_HEAT = "NO_HEAT"
    NO_POWER = "NO_POWER"
    LOCKOUT = "LOCKOUT"
    LEAK_MINOR = "LEAK_MINOR"
    APPLIANCE = "APPLIANCE"
    OTHER = "OTHER"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class WorkOrderPriority(str, Enum):
    EMERGENCY_FOLLOWUP = "EMERGENCY_FOLLOWUP"
    DEFERRED = "DEFERRED"
    STANDARD = "STANDARD"


class VendorAuthorizationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class RelocationCaseStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    REJECTED = "REJECTED"


class IncidentRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    FINALIZED = "FINALIZED"


class PayPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class UserRole(str, Enum):
    PROPERTY_ADMIN = "PropertyAdmin"
    DISPATCHER = "Dispatcher"
    ON_CALL_TECHNICIAN = "OnCallTechnician"
    MAINTENANCE_SUPERVISOR = "MaintenanceSupervisor"
    VENDOR = "Vendor"


# --- Entity TypedDicts -------------------------------------------------------
# All primary resources carry id / created_at / updated_at / version (PRD §2.5).
# PayStatement is the single exception: id + created_at only.


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    capability: str
    base_hourly_rate_cents: int
    on_call_differential_bp: int
    status: str
    callback_minutes_168h: int
    fatigue_block_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    unit_number: str
    building_code: str
    habitability_status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    name: str
    trade: str
    per_incident_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RotationShift(TypedDict, total=False):
    id: str
    technician_id: str
    start_at: str
    end_at: str
    status: str
    needs_coverage: bool
    standby_minutes: Optional[int]
    provisional_shift_pay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CallTicket(TypedDict, total=False):
    id: str
    unit_id: str
    caller_name: str
    caller_phone: str
    category: str
    description: str
    received_at: str
    is_true_emergency: Optional[bool]
    status: str
    sla_target_minutes: Optional[int]
    assigned_technician_id: Optional[str]
    triaged_at: Optional[str]
    dispatched_at: Optional[str]
    on_scene_at: Optional[str]
    mitigated_at: Optional[str]
    closed_at: Optional[str]
    response_minutes: Optional[int]
    response_breach: Optional[bool]
    escalation_level: int
    unit_declared_uninhabitable: bool
    callback_minutes: Optional[int]
    callback_pay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    call_ticket_id: str
    unit_id: str
    parent_work_order_id: Optional[str]
    title: str
    description: str
    priority: str
    status: str
    assigned_technician_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorAuthorization(TypedDict, total=False):
    id: str
    call_ticket_id: str
    work_order_id: str
    vendor_id: str
    amount_cents: int
    requested_by_technician_id: str
    authorized_by_technician_id: Optional[str]
    status: str
    invoice_subtotal_cents: Optional[int]
    invoice_markup_cents: Optional[int]
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RelocationCase(TypedDict, total=False):
    id: str
    unit_id: str
    call_ticket_id: str
    proposed_by_technician_id: str
    approved_by_technician_id: Optional[str]
    start_date: str
    end_date: str
    nightly_rate_cents: int
    planned_nights: int
    est_cost_cents: int
    actual_cost_cents: Optional[int]
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentRecord(TypedDict, total=False):
    id: str
    call_ticket_id: str
    narrative: str
    estimated_damage_cents: int
    status: str
    created_by_technician_id: str
    insurance_notified_at: Optional[str]
    insurance_claim_number: Optional[str]
    insurance_notification_late: Optional[bool]
    insurance_waived_reason: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayPeriod(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayStatement(TypedDict, total=False):
    # Emitted once at period close and never mutated: only id + created_at
    # exist alongside the statement payload (PRD §2.5).
    id: str
    created_at: str
    pay_period_id: str
    technician_id: str
    standby_minutes_total: int
    standby_pay_final_cents: int
    callback_minutes_total: int
    callback_pay_final_cents: int
    total_pay_cents: int
