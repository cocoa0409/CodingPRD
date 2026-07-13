"""Domain types for the Integrated Facilities Management API.

Entity TypedDicts, status enums and the role enum, all derived from the PRD.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FACILITY_MANAGER = "FacilityManager"
    VENDOR_TECH = "VendorTech"
    FINANCE_CONTROLLER = "FinanceController"
    TENANT_REP = "TenantRep"
    SUSTAINABILITY_ANALYST = "SustainabilityAnalyst"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class OperatingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class SpaceType(str, Enum):
    OFFICE = "OFFICE"
    LAB = "LAB"
    RETAIL = "RETAIL"
    COMMON = "COMMON"
    PLANT = "PLANT"


class OccupancyStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"


class AssetCategory(str, Enum):
    HVAC = "HVAC"
    ELEVATOR = "ELEVATOR"
    FIRE = "FIRE"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"


class AssetCriticality(str, Enum):
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"
    LOW = "LOW"


class AssetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class PMPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ComplianceState(str, Enum):
    ON_TIME = "ON_TIME"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class VendorTrade(str, Enum):
    HVAC = "HVAC"
    ELEVATOR = "ELEVATOR"
    FIRE = "FIRE"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    JANITORIAL = "JANITORIAL"
    SECURITY = "SECURITY"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class WorkOrderType(str, Enum):
    CORRECTIVE = "CORRECTIVE"
    PREVENTIVE = "PREVENTIVE"
    SOFT_SERVICE = "SOFT_SERVICE"


class WorkOrderPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class WorkOrderStatus(str, Enum):
    NEW = "NEW"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_QA = "PENDING_QA"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    SETTLED_CHARGEBACK = "SETTLED_CHARGEBACK"
    WAIVED = "WAIVED"


class SlaState(str, Enum):
    WITHIN = "WITHIN"
    RESPONSE_BREACHED = "RESPONSE_BREACHED"
    RESOLVE_BREACHED = "RESOLVE_BREACHED"


class DispatchStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    JANITORIAL = "JANITORIAL"
    SECURITY = "SECURITY"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class MeterType(str, Enum):
    ELECTRIC = "ELECTRIC"
    GAS = "GAS"
    WATER = "WATER"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_FLIGHT = "IN_FLIGHT"
    CLOSED = "CLOSED"


class QaOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ProjectDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Every persisted resource carries id + created_at. Almost every resource also
# carries updated_at and version — the single exception is UtilityReading, an
# append-only measurement record that exposes only id and created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class Building(TypedDict):
    id: str
    name: str
    code: str
    gross_area_sqm: float
    region: Optional[str]
    operating_posture: str
    oos_critical_asset_count: int
    open_p1_work_order_count: int
    created_at: str
    updated_at: str
    version: int


class Space(TypedDict):
    id: str
    building_id: str
    space_code: str
    floor: int
    area_sqm: float
    space_type: str
    cost_center: Optional[str]
    allocated_share_pct: float
    free_share_pct: float
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    building_id: str
    asset_tag: str
    category: str
    criticality: str
    status: str
    runtime_hours: float
    failure_count: int
    condition_score: float
    last_pm_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PMPlan(TypedDict):
    id: str
    asset_id: str
    interval_days: int
    grace_days: int
    next_due_at: str
    status: str
    compliance_state: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    trade: str
    hourly_rate: float
    sla_response_minutes: int
    sla_resolve_minutes: int
    status: str
    strike_count: int
    performance_score: float
    lifetime_performance_score: float
    completed_dispatch_count: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    building_id: str
    asset_id: Optional[str]
    pm_plan_id: Optional[str]
    funding_project_id: Optional[str]
    statement_id: Optional[str]
    wo_type: str
    priority: str
    chargeable: bool
    estimated_labor_hours: float
    estimated_parts_cost: float
    actual_labor_hours: Optional[float]
    actual_parts_cost: Optional[float]
    estimated_amount: float
    billable_amount: Optional[float]
    status: str
    billing_status: str
    failed_qa_count: int
    dispatched_at: Optional[str]
    sla_response_due_at: Optional[str]
    sla_resolve_due_at: Optional[str]
    sla_state: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    work_order_id: str
    vendor_id: str
    status: str
    dispatched_at: str
    accepted_at: Optional[str]
    completed_at: Optional[str]
    response_minutes: Optional[int]
    resolve_minutes: Optional[int]
    sla_response_met: Optional[bool]
    sla_resolve_met: Optional[bool]
    penalty_pct: float
    actual_labor_hours: Optional[float]
    actual_parts_cost: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SoftServiceShift(TypedDict):
    id: str
    building_id: str
    vendor_id: str
    zone_space_id: str
    service_type: str
    start_at: str
    end_at: str
    planned_headcount: int
    actual_headcount: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityReading(TypedDict):
    """Append-only measurement record: only id and created_at (PRD §2.4)."""

    id: str
    building_id: str
    meter_type: str
    period_start: str
    period_end: str
    consumption_kwh: float
    cost: float
    created_at: str


class Lease(TypedDict):
    id: str
    building_id: str
    tenant_name: str
    base_rate_per_sqm_month: float
    start_date: str
    end_date: str
    status: str
    allocated_area_sqm: float
    created_at: str
    updated_at: str
    version: int


class LeaseAllocation(TypedDict):
    id: str
    lease_id: str
    space_id: str
    share_pct: float
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargebackStatement(TypedDict):
    id: str
    lease_id: str
    period_start: str
    period_end: str
    base_rent: float
    utility_share: float
    om_share: float
    total_amount: float
    status: str
    dispute_reason: Optional[str]
    issued_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict):
    id: str
    building_id: str
    title: str
    base_cost: float
    contingency_pct: float
    contingency_amount: float
    budget_amount: float
    committed_amount: float
    spent_amount: float
    remaining_amount: float
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildingKpi(TypedDict):
    posture: str
    energy_intensity_kwh_per_sqm: float
    total_utility_cost: float
    open_work_order_count: int
    sla_compliance_pct: float
    pm_compliance_pct: float
    occupancy_pct: float


class OpsRunResult(TypedDict):
    posture: str
    created_work_order_ids: list
    in_progress_shift_ids: list
    missed_shift_ids: list
    retired_asset_ids: list
    expired_lease_ids: list
    closed_project_ids: list
