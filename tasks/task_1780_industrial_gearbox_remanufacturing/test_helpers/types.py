"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    REMAN_ENGINEER = "RemanEngineer"
    QUALITY_INSPECTOR = "QualityInspector"
    SERVICE_MANAGER = "ServiceManager"
    CUSTOMER = "Customer"


class PhysicalStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    AT_SHOP = "AT_SHOP"
    SCRAPPED = "SCRAPPED"


class CommercialStatus(str, Enum):
    STANDARD = "STANDARD"
    UNDER_WARRANTY_REVIEW = "UNDER_WARRANTY_REVIEW"
    WARRANTY_FLAGGED = "WARRANTY_FLAGGED"


class OrderStatus(str, Enum):
    INTAKE = "INTAKE"
    TEARDOWN = "TEARDOWN"
    SCOPE_APPROVAL = "SCOPE_APPROVAL"
    APPROVED = "APPROVED"
    IN_BUILD = "IN_BUILD"
    ASSEMBLY = "ASSEMBLY"
    RUN_IN = "RUN_IN"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FindingCondition(str, Enum):
    REUSABLE = "REUSABLE"
    REGRINDABLE = "REGRINDABLE"
    CUT_ONLY = "CUT_ONLY"
    BEYOND_REPAIR = "BEYOND_REPAIR"


class DecisionAction(str, Enum):
    REGRIND = "REGRIND"
    CUT_NEW = "CUT_NEW"
    REPLACE_OEM = "REPLACE_OEM"
    REUSE_AS_IS = "REUSE_AS_IS"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class AssemblyRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"


class RunInResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RunInTestStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class LoanerUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"


class LoanerAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ShipmentDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class ShipmentStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimEligibility(str, Enum):
    COVERED = "COVERED"
    EXPIRED_HOURS = "EXPIRED_HOURS"
    EXPIRED_CALENDAR = "EXPIRED_CALENDAR"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id, created_at, updated_at, version (PRD §2.4).
# TeardownFinding is the append-only exception: only id and created_at.


class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    credit_limit_cents: int
    outstanding_approved_cents: int
    credit_hold: bool
    created_at: str
    updated_at: str
    version: int


class GearUnit(TypedDict, total=False):
    id: str
    customer_id: str
    serial_number: str
    model: str
    rated_torque_nm: int
    cumulative_service_hours: int
    physical_status: str
    commercial_status: str
    created_at: str
    updated_at: str
    version: int


class RemanOrder(TypedDict, total=False):
    id: str
    gear_unit_id: str
    intake_hours: int
    quoted_estimate_cents: int
    approved_scope_cents: int
    final_invoice_cents: Optional[int]
    rush: bool
    status: str
    completed_at_hours: Optional[int]
    completed_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeardownFinding(TypedDict, total=False):
    # Append-only log (PRD §2.4): carries ONLY id and created_at —
    # no updated_at, no version.
    id: str
    created_at: str
    reman_order_id: str
    component_code: str
    condition: str
    severity: int
    notes: str


class ComponentDecision(TypedDict, total=False):
    id: str
    reman_order_id: str
    component_code: str
    action: str
    labor_hours: float
    material_cents: int
    line_total_cents: int
    approval_status: str
    created_at: str
    updated_at: str
    version: int


class AssemblyRecord(TypedDict, total=False):
    id: str
    reman_order_id: str
    backlash_mm: float
    radial_clearance_mm: float
    axial_clearance_mm: float
    recorded_by: str
    within_tolerance: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RunInTest(TypedDict, total=False):
    id: str
    reman_order_id: str
    duration_minutes: int
    max_temp_c: float
    vibration_mm_s: float
    oil_particle_count: int
    oil_baseline_established: bool
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanerUnit(TypedDict, total=False):
    id: str
    serial_number: str
    model: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanerAssignment(TypedDict, total=False):
    id: str
    loaner_unit_id: str
    reman_order_id: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FreightShipment(TypedDict, total=False):
    id: str
    reman_order_id: str
    direction: str
    weight_kg: int
    rigging_bay_date: str
    rigging_bay_hours: int
    freight_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    reman_order_id: str
    reported_hours: int
    claim_reason: str
    hours_since_reman: Optional[int]
    warranty_clock_start_hours: Optional[int]
    eligibility: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
