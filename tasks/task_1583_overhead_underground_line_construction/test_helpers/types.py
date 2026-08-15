"""Domain types: entity TypedDicts, status enums, and the role enum.

Mirrors the resource model in PRD §2.4 (every resource carries id, created_at,
updated_at, version) and §3 (per-entity fields and lifecycle states).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CONTRACTOR_PM = "CONTRACTOR_PM"
    FOREMAN = "FOREMAN"
    UTILITY_INSPECTOR = "UTILITY_INSPECTOR"
    UTILITY_DISPATCHER = "UTILITY_DISPATCHER"
    SAFETY_OFFICER = "SAFETY_OFFICER"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BidItemUnit(str, Enum):
    EACH = "EACH"
    LF = "LF"
    CY = "CY"
    HR = "HR"


class WorkPackageStatus(str, Enum):
    PLANNED = "PLANNED"
    MOBILIZED = "MOBILIZED"
    IN_PROGRESS = "IN_PROGRESS"
    PUNCH = "PUNCH"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CrewType(str, Enum):
    OVERHEAD = "OVERHEAD"
    UNDERGROUND = "UNDERGROUND"
    STORM = "STORM"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    STANDBY = "STANDBY"
    CALLOUT = "CALLOUT"


class EquipmentKind(str, Enum):
    BUCKET_TRUCK = "BUCKET_TRUCK"
    DIGGER_DERRICK = "DIGGER_DERRICK"
    TRENCHER = "TRENCHER"
    REEL_TRAILER = "REEL_TRAILER"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"


class AssignmentStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProductionEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    VOID = "VOID"


class MaterialIssueStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    VARIANCE_RECONCILED = "VARIANCE_RECONCILED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class OutageRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CHANGE_REQUESTED = "CHANGE_REQUESTED"
    IN_EFFECT = "IN_EFFECT"
    RELEASED = "RELEASED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class StormActivationKind(str, Enum):
    STANDBY = "STANDBY"
    CALLOUT = "CALLOUT"


class StormActivationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SafetyEventKind(str, Enum):
    OBSERVATION = "OBSERVATION"
    INCIDENT = "INCIDENT"


class SafetyEventSeverity(str, Enum):
    POSITIVE = "POSITIVE"
    AT_RISK = "AT_RISK"
    OSHA_RECORDABLE = "OSHA_RECORDABLE"
    FATAL = "FATAL"


class SafetyEventStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    VOID = "VOID"


class HoldReason(str, Enum):
    OPEN_REWORK = "OPEN_REWORK"


class Contract(TypedDict, total=False):
    id: str
    utility_name: str
    contract_number: str
    effective_start: str
    effective_end: str
    retainage_pct: float
    overrun_threshold_pct: float
    quantity_cap_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BidItem(TypedDict, total=False):
    id: str
    contract_id: str
    item_code: str
    description: str
    unit: str
    unit_price: float
    estimated_quantity: float
    overrun_rate: Optional[float]
    accepted_quantity: float
    billed_quantity: float
    created_at: str
    updated_at: str
    version: int


class WorkPackage(TypedDict, total=False):
    id: str
    contract_id: str
    name: str
    location: str
    requires_outage: bool
    status: str
    rework_open_count: int
    open_material_issue_count: int
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    crew_code: str
    crew_type: str
    base_rate_per_hour: float
    home_depot: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    equipment_code: str
    kind: str
    daily_rate: float
    maintenance_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    work_package_id: str
    crew_id: str
    equipment_id: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionEntry(TypedDict, total=False):
    id: str
    assignment_id: str
    bid_item_id: str
    work_date: str
    quantity_reported: float
    rework_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StockItem(TypedDict, total=False):
    id: str
    contract_id: str
    material_code: str
    description: str
    uom: str
    initial_on_hand: float
    on_hand: float
    created_at: str
    updated_at: str
    version: int


class MaterialIssue(TypedDict, total=False):
    id: str
    work_package_id: str
    stock_item_id: str
    quantity_issued: float
    quantity_returned: float
    quantity_installed: Optional[float]
    variance: Optional[float]
    variance_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    work_package_id: str
    production_entry_id: str
    standard_code: str
    result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutageRequest(TypedDict, total=False):
    id: str
    work_package_id: str
    circuit_id: str
    window_start: str
    window_end: str
    requested_window_start: Optional[str]
    requested_window_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StormActivation(TypedDict, total=False):
    id: str
    contract_id: str
    crew_id: str
    kind: str
    activation_date: str
    hours_standby: Optional[float]
    hours_worked: Optional[float]
    premium_pay: Optional[float]
    converted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyEvent(TypedDict, total=False):
    id: str
    work_package_id: str
    crew_id: Optional[str]
    kind: str
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    bid_item_id: str
    item_code: str
    in_schedule_units: float
    overrun_units: float
    in_schedule_rate: float
    overrun_rate_applied: float
    extension_amount: float


class Invoice(TypedDict, total=False):
    id: str
    work_package_id: str
    period_start: str
    period_end: str
    lines: List[InvoiceLine]
    subtotal: float
    retainage_amount: float
    amount_due: float
    hold_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
