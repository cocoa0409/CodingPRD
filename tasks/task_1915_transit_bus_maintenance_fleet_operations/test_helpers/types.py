"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the PRD §2.4 common fields (id, created_at, updated_at,
version).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    FLEET_MANAGER = "FleetManager"
    MAINTENANCE_SUPERVISOR = "MaintenanceSupervisor"
    MECHANIC = "Mechanic"
    OPERATOR = "Operator"
    PARTS_CLERK = "PartsClerk"
    WARRANTY_CLERK = "WarrantyClerk"


class BusServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERHAUL_HOLD = "OVERHAUL_HOLD"
    RETIRED = "RETIRED"


class BusAvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_SHOP = "IN_SHOP"
    HELD = "HELD"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class HoldReason(str, Enum):
    SAFETY = "SAFETY"
    EMISSIONS = "EMISSIONS"
    ROAD_CALL = "ROAD_CALL"
    TOWED = "TOWED"


class EmissionsCompliance(str, Enum):
    COMPLIANT = "COMPLIANT"
    CERT_EXPIRED = "CERT_EXPIRED"
    NON_COMPLIANT = "NON_COMPLIANT"


class PmDueStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE_SOON = "DUE_SOON"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class PMPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CertType(str, Enum):
    ENGINE = "ENGINE"
    TRANSMISSION = "TRANSMISSION"
    BRAKES = "BRAKES"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    EMISSIONS = "EMISSIONS"
    PM_INSPECTION = "PM_INSPECTION"
    QA_AUTHORITY = "QA_AUTHORITY"


class CertStatus(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"


class ShiftType(str, Enum):
    AM = "AM"
    PM = "PM"
    NIGHT = "NIGHT"


class ShiftStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    RECONCILED = "RECONCILED"


class CoverageStatus(str, Enum):
    FULL = "FULL"
    SHORT = "SHORT"


class RoleInShift(str, Enum):
    LEAD = "LEAD"
    TECH = "TECH"
    QA = "QA"


class ShiftAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    REMOVED = "REMOVED"


class PartClass(str, Enum):
    CONSUMABLE = "CONSUMABLE"
    REBUILDABLE_CORE = "REBUILDABLE_CORE"
    EXPENDABLE = "EXPENDABLE"


class StockStatus(str, Enum):
    NORMAL = "NORMAL"
    LOW_STOCK = "LOW_STOCK"
    BACKORDERED = "BACKORDERED"


class WorkOrderType(str, Enum):
    PM_A = "PM_A"
    PM_B = "PM_B"
    PM_C = "PM_C"
    CAMPAIGN = "CAMPAIGN"
    CORRECTIVE = "CORRECTIVE"
    EMISSIONS = "EMISSIONS"
    OVERHAUL = "OVERHAUL"


class WorkOrderPriority(str, Enum):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"
    ELECTIVE = "ELECTIVE"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    PENDING_QA = "PENDING_QA"
    REOPENED = "REOPENED"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PartLineIssueStatus(str, Enum):
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"


class CoreStatus(str, Enum):
    NONE = "NONE"
    CORE_PENDING = "CORE_PENDING"
    CORE_LATE = "CORE_LATE"
    CORE_CREDITED = "CORE_CREDITED"
    CORE_REJECTED = "CORE_REJECTED"


class DefectSeverity(str, Enum):
    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class DefectCode(str, Enum):
    ENGINE = "ENGINE"
    TRANSMISSION = "TRANSMISSION"
    BRAKES = "BRAKES"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    FUEL_SYSTEM = "FUEL_SYSTEM"
    TIRE = "TIRE"
    OTHER = "OTHER"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    ROAD_CALL_DISPATCHED = "ROAD_CALL_DISPATCHED"
    ON_SCENE = "ON_SCENE"
    SHOP_QUEUED = "SHOP_QUEUED"
    WO_LINKED = "WO_LINKED"
    DEFERRED = "DEFERRED"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class DefectDisposition(str, Enum):
    SHOP = "SHOP"
    ROAD_CALL = "ROAD_CALL"
    DEFER = "DEFER"


class DefectResolution(str, Enum):
    SHOP_REPAIRED = "SHOP_REPAIRED"
    ROAD_CALL_FIXED = "ROAD_CALL_FIXED"
    TOWED_IN = "TOWED_IN"
    MANUAL = "MANUAL"
    AUTO_VOIDED = "AUTO_VOIDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class MileageFuelLogStatus(str, Enum):
    POSTED = "POSTED"
    FLAGGED = "FLAGGED"
    VOIDED = "VOIDED"


class TestType(str, Enum):
    OPACITY = "OPACITY"
    OBD = "OBD"
    IDLE = "IDLE"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ClaimType(str, Enum):
    BASE_OEM = "BASE_OEM"
    EXTENDED = "EXTENDED"
    PARTS_ONLY = "PARTS_ONLY"
    GOODWILL = "GOODWILL"


class ProrationBasis(str, Enum):
    MILES = "MILES"
    TIME = "TIME"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    RECOVERED = "RECOVERED"
    WITHDRAWN = "WITHDRAWN"


class ReplacementPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    CLOSED = "CLOSED"


class PostureTier(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry PRD §2.4 common fields)
# ---------------------------------------------------------------------------


class Bus(TypedDict, total=False):
    id: str
    fleet_number: str
    vin: str
    model_year: int
    in_service_date: str
    initial_odometer_miles: int
    odometer_miles: int
    replacement_cost_cents: int
    base_warranty_expiry_miles: int
    base_warranty_expiry_date: str
    extended_warranty_limit_miles: Optional[int]
    extended_warranty_limit_months: Optional[int]
    overhaul_interval_miles: int
    last_overhaul_miles: int
    service_status: str
    availability_status: str
    hold_reasons: List[str]
    emissions_cert_expiry_date: Optional[str]
    emissions_compliance: str
    last_pm_a_miles: int
    last_pm_a_date: str
    last_pm_b_miles: int
    last_pm_b_date: str
    last_pm_c_miles: int
    last_pm_c_date: str
    pm_due_status: str
    total_maintenance_cost_cents: int
    retirement_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PMPolicy(TypedDict, total=False):
    id: str
    level_a_interval_miles: int
    level_b_interval_miles: int
    level_c_interval_miles: int
    tolerance_miles: int
    calendar_interval_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Mechanic(TypedDict, total=False):
    id: str
    name: str
    employee_ref: str
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class MechanicCertification(TypedDict, total=False):
    id: str
    mechanic_id: str
    cert_type: str
    issued_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    shift_date: str
    shift_type: str
    required_headcount: Dict[str, int]
    status: str
    coverage_by_cert: Dict[str, int]
    coverage_status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    shift_id: str
    mechanic_id: str
    role_in_shift: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    sku: str
    description: str
    part_class: str
    unit_cost_cents: int
    reorder_point: int
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int
    stock_status: str
    core_charge_cents: Optional[int]
    warranty_eligible: bool
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaborEntry(TypedDict, total=False):
    work_date: str
    shift_type: str
    hours: float
    mechanic_id: str
    amount_cents: int


class WorkOrder(TypedDict, total=False):
    id: str
    bus_id: str
    wo_type: str
    priority: str
    defect_report_id: Optional[str]
    campaign_id: Optional[str]
    emissions_inspection_id: Optional[str]
    lead_mechanic_id: Optional[str]
    planned_start_date: str
    planned_end_date: str
    estimated_labor_hours: float
    estimated_cost_cents: int
    odometer_at_open: int
    opened_date: str
    started_date: Optional[str]
    closed_date: Optional[str]
    status: str
    labor_entries: List[LaborEntry]
    labor_total_cents: int
    parts_total_cents: int
    core_charges_accrued_cents: int
    core_credits_cents: int
    parts_net_cents: int
    total_cost_cents: int
    qa_reject_count: int
    qa_note: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrderPartLine(TypedDict, total=False):
    id: str
    work_order_id: str
    part_id: str
    qty: int
    qty_issued: int
    unit_cost_cents: int
    issue_status: str
    core_status: str
    core_due_date: Optional[str]
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class DefectReport(TypedDict, total=False):
    id: str
    bus_id: str
    reported_by: str
    severity: str
    defect_code: str
    description: str
    odometer_at_report: int
    status: str
    disposition: Optional[str]
    road_call_mechanic_id: Optional[str]
    defer_until_date: Optional[str]
    defer_justification: Optional[str]
    defer_count: int
    linked_work_order_id: Optional[str]
    resolution: Optional[str]
    flagged_by_log_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    code: str
    title: str
    model_year_from: int
    model_year_to: int
    required_part_id: Optional[str]
    required_cert_type: Optional[str]
    labor_hours_per_bus: float
    deadline_date: str
    status: str
    scope_bus_ids: List[str]
    activated_date: Optional[str]
    buses_completed_count: int
    progress_pct: float
    created_at: str
    updated_at: str
    version: int


class MileageFuelLog(TypedDict, total=False):
    id: str
    bus_id: str
    log_date: str
    odometer_end: int
    fuel_gallons: int
    miles_driven: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionsInspection(TypedDict, total=False):
    id: str
    bus_id: str
    test_type: str
    test_date: str
    result: str
    failed_component_part_id: Optional[str]
    certificate_expiry_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    work_order_id: str
    bus_id: str
    claim_type: str
    proration_basis: Optional[str]
    manual_claimed_cents: Optional[int]
    status: str
    eligible_cents: Optional[int]
    claimed_cents: Optional[int]
    approved_cents: Optional[int]
    received_cents: Optional[int]
    variance_cents: Optional[int]
    appeal_count: int
    oem_reference: Optional[str]
    auto_created: bool
    submitted_by_user_id: Optional[str]
    recovered_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FleetReplacementPlan(TypedDict, total=False):
    id: str
    plan_year: int
    status: str
    scores: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int
