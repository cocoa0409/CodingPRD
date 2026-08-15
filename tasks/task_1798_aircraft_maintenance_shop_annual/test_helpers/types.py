"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AirworthinessPosture(str, Enum):
    AIRWORTHY = "AIRWORTHY"
    RESTRICTED = "RESTRICTED"
    GROUNDED = "GROUNDED"


class MechanicStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CertificateClass(str, Enum):
    AP = "AP"
    IA = "IA"


class HangarSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    INSPECTION_COMPLETE = "INSPECTION_COMPLETE"
    AWAITING_OWNER_APPROVAL = "AWAITING_OWNER_APPROVAL"
    APPROVED = "APPROVED"
    WORK_IN_PROGRESS = "WORK_IN_PROGRESS"
    READY_FOR_RTS = "READY_FOR_RTS"
    RETURNED_TO_SERVICE = "RETURNED_TO_SERVICE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ScopeType(str, Enum):
    ANNUAL = "ANNUAL"
    HUNDRED_HOUR = "HUNDRED_HOUR"
    UNSCHEDULED = "UNSCHEDULED"


class PricingMode(str, Enum):
    HOURLY = "HOURLY"
    FLAT_RATE = "FLAT_RATE"


class ChecklistResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"


class DiscrepancyStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_OWNER_DECISION = "PENDING_OWNER_DECISION"
    APPROVED = "APPROVED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    RECTIFIED = "RECTIFIED"
    VERIFIED = "VERIFIED"


class Severity(str, Enum):
    AIRWORTHINESS = "AIRWORTHINESS"
    NON_AIRWORTHINESS = "NON_AIRWORTHINESS"


class DirectiveType(str, Enum):
    AD = "AD"
    SB = "SB"


class ComplianceStatus(str, Enum):
    PENDING_EVALUATION = "PENDING_EVALUATION"
    APPLICABLE_OPEN = "APPLICABLE_OPEN"
    COMPLIED = "COMPLIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PartCondition(str, Enum):
    NEW = "NEW"
    OVERHAUL = "OVERHAUL"
    SERVICEABLE = "SERVICEABLE"


class PartStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SOURCED = "SOURCED"
    RECEIVED = "RECEIVED"
    INSTALLED = "INSTALLED"
    RETURNED = "RETURNED"


class LaborEntryStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class LogbookEntryType(str, Enum):
    INSPECTION_SIGNOFF = "INSPECTION_SIGNOFF"
    REPAIR_RECORD = "REPAIR_RECORD"
    RTS_STATEMENT = "RTS_STATEMENT"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    MECHANIC = "Mechanic"
    OWNER = "Owner"
    PARTS_CLERK = "PartsClerk"


# --- Entities with common_fields: true ---


class Owner(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    approval_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    owner_id: str
    tail_number: str
    make_model: str
    total_time_hours: float
    airworthiness_posture: str
    posture_reason: str
    created_at: str
    updated_at: str
    version: int


class Mechanic(TypedDict, total=False):
    id: str
    full_name: str
    certificate_number: str
    certificate_class: str
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HangarSlot(TypedDict, total=False):
    id: str
    hangar_code: str
    aircraft_id: str
    starts_at: str
    ends_at: str
    daily_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    aircraft_id: str
    hangar_slot_id: str
    opened_by_mechanic_id: str
    scope_type: str
    pricing_mode: str
    status: str
    open_discrepancy_count: int
    verified_discrepancy_count: int
    labor_hours_tenths: int
    created_at: str
    updated_at: str
    version: int


class Discrepancy(TypedDict, total=False):
    id: str
    work_order_id: str
    checklist_item_id: Optional[str]
    description: str
    severity: str
    estimated_cost_cents: int
    status: str
    requires_owner_decision: bool
    decided_by_owner_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Directive(TypedDict, total=False):
    id: str
    aircraft_id: str
    directive_type: str
    reference_number: str
    description: str
    compliance_status: str
    evaluated_by_mechanic_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    discrepancy_id: str
    part_number: str
    serial_number: Optional[str]
    condition: str
    trace_doc_ref: Optional[str]
    unit_cost_cents: int
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    work_order_id: str
    labor_charge_cents: int
    parts_charge_cents: int
    shop_supplies_cents: int
    hangar_fee_cents: int
    tax_cents: int
    total_cents: int
    warranty_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Entities with common_fields: false (append-only / ledger-like) ---
# These carry ONLY id + created_at — no updated_at, no version.


class ChecklistItem(TypedDict, total=False):
    id: str
    work_order_id: str
    item_code: str
    description: str
    flat_rate_cents: int
    result: str
    inspected_by_mechanic_id: Optional[str]
    created_at: str


class LaborEntry(TypedDict, total=False):
    id: str
    work_order_id: str
    mechanic_id: str
    duration_tenths: int
    notes: str
    status: str
    created_at: str


class LogbookEntry(TypedDict, total=False):
    id: str
    aircraft_id: str
    work_order_id: str
    entry_type: str
    narrative: str
    signed_by_mechanic_id: str
    signed_at: str
    created_at: str
