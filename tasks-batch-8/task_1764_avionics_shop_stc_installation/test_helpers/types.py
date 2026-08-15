"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    TECHNICIAN = "Technician"
    INSPECTOR = "Inspector"
    CUSTOMER = "Customer"


class CustomerKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FLIGHT_SCHOOL = "FLIGHT_SCHOOL"
    FLEET_OPERATOR = "FLEET_OPERATOR"


class AircraftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_SHOP = "IN_SHOP"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PARTS_PENDING = "PARTS_PENDING"
    INSTALLATION = "INSTALLATION"
    TESTING = "TESTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PanelDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class EquipmentOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class EquipmentOrderSource(str, Enum):
    DESIGN_RELEASE = "DESIGN_RELEASE"
    MANUAL = "MANUAL"


class InstallTaskStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class TaskKind(str, Enum):
    HARNESS_FABRICATION = "HARNESS_FABRICATION"
    PANEL_ASSEMBLY = "PANEL_ASSEMBLY"
    INSTALLATION = "INSTALLATION"


class TestKind(str, Enum):
    GROUND = "GROUND"
    FLIGHT = "FLIGHT"


class TestEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TestResult(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL = "FAIL"


class ApprovalPath(str, Enum):
    STC = "STC"
    FIELD_APPROVAL = "FIELD_APPROVAL"


class RegulatoryPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFORMITY_REVIEW = "CONFORMITY_REVIEW"
    FAA_SUBMITTED = "FAA_SUBMITTED"
    APPROVED = "APPROVED"


class WBMethod(str, Enum):
    INCREMENTAL = "INCREMENTAL"
    FULL_REWEIGH = "FULL_REWEIGH"


class WBRevisionStatus(str, Enum):
    COMPUTED = "COMPUTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class DecideOutcome(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class RegulatoryDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity bodies — every resource carries the common quartet
# (id / created_at / updated_at / version) per PRD §2.4.
# ---------------------------------------------------------------------------


class Customer(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    customer_kind: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    customer_id: str
    tail_number: str
    make_model: str
    baseline_empty_weight_lb: float
    baseline_arm_in: float
    baseline_moment_lb_in: float
    cg_min_arm_in: float
    cg_max_arm_in: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    aircraft_id: str
    scope_description: str
    estimated_downtime_days: int
    quoted_labor_hours: float
    bay_code: str
    bay_window_start: str
    bay_window_end: str
    status: str
    inducted_at: Optional[str]
    completed_at: Optional[str]
    actual_downtime_days: Optional[int]
    downtime_overage_days: Optional[int]
    overage_acknowledged: bool
    parts_pending_count: int
    tasks_unverified_count: int
    total_actual_labor_hours: float
    total_billed_labor_cents: int
    quoted_total_cents: Optional[int]
    warranty_term_months: int
    software_subscription_months: int
    warranty_expires_at: Optional[str]
    subscription_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentLine(TypedDict, total=False):
    part_number: str
    description: str
    quantity: int
    unit_price_cents: int
    weight_lb: float
    arm_in: float
    lead_time_days: int


class PanelDesign(TypedDict, total=False):
    id: str
    work_order_id: str
    revision: int
    layout_notes: str
    equipment_list: List[Dict[str, Any]]
    total_added_weight_lb: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentOrder(TypedDict, total=False):
    id: str
    work_order_id: str
    seq: int
    source: str
    source_design_revision: Optional[int]
    part_number: str
    description: str
    quantity: int
    unit_price_cents: int
    lead_time_days: int
    ordered_at: Optional[str]
    promised_date: Optional[str]
    received_at: Optional[str]
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallTask(TypedDict, total=False):
    id: str
    work_order_id: str
    task_kind: str
    description: str
    estimated_hours: float
    actual_hours: Optional[float]
    performed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    billed_labor_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestEvent(TypedDict, total=False):
    id: str
    work_order_id: str
    test_kind: str
    scheduled_start: str
    scheduled_end: str
    attempt: int
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryPackage(TypedDict, total=False):
    id: str
    work_order_id: str
    approval_path: str
    stc_number: Optional[str]
    faa_tracking_number: Optional[str]
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AddedItem(TypedDict, total=False):
    description: str
    weight_lb: float
    arm_in: float


class WeightBalanceRevision(TypedDict, total=False):
    id: str
    work_order_id: str
    method: str
    added_items: List[Dict[str, Any]]
    removed_weight_lb: float
    removed_arm_in: Optional[float]
    new_empty_weight_lb: float
    new_moment_lb_in: float
    new_arm_in: float
    cg_within_limits: bool
    status: str
    created_at: str
    updated_at: str
    version: int
