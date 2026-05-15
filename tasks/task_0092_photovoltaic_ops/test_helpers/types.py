"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4: most resources carry id/created_at/updated_at/version.
GenerationReading, MeteringRecord, RevenueDistribution, AlarmCodeMap,
and AuditEntry are append-only — only id + created_at.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OM_ENGINEER = "O&MEngineer"
    FIELD_OPERATOR = "FieldOperator"
    FINANCE_OFFICER = "FinanceOfficer"


# ---------------------------------------------------------------------------
# Status / enum-typed fields (PRD §3.*)
# ---------------------------------------------------------------------------
class StationOperationalStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class StationLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ModuleLifecycleState(str, Enum):
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"
    RETURN_TO_VENDOR = "RETURN_TO_VENDOR"
    SCRAPPED = "SCRAPPED"


class InverterRole(str, Enum):
    INVERTER = "INVERTER"
    COMBINER_BOX = "COMBINER_BOX"


class InverterLifecycleState(str, Enum):
    OPERATING = "OPERATING"
    UNDER_REPAIR = "UNDER_REPAIR"
    RETIRED = "RETIRED"


class SupplierRating(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class SupplierLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    BLACKLISTED = "BLACKLISTED"


class GenerationGranularity(str, Enum):
    RAW_1MIN = "RAW_1MIN"
    AGG_15MIN = "AGG_15MIN"
    AGG_1H = "AGG_1H"
    AGG_1DAY = "AGG_1DAY"


class AlarmSeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class AlarmState(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLEARED = "CLEARED"
    ARCHIVED = "ARCHIVED"


class PatrolKind(str, Enum):
    PERIODIC = "PERIODIC"
    SPECIAL_POST_STORM = "SPECIAL_POST_STORM"


class PatrolPlanLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PatrolRecordState(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DefectSubjectType(str, Enum):
    INVERTER = "INVERTER"
    MODULE = "MODULE"
    TRANSFORMER = "TRANSFORMER"
    STRING = "STRING"
    ARRAY = "ARRAY"


class DefectSource(str, Enum):
    ALARM = "ALARM"
    PATROL = "PATROL"
    DATA_ANOMALY = "DATA_ANOMALY"
    EXTERNAL_INSPECTION = "EXTERNAL_INSPECTION"


class DefectSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DefectState(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    UNDER_REPAIR = "UNDER_REPAIR"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class WorkOrderState(str, Enum):
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class PricingChannel(str, Enum):
    FEED_IN = "FEED_IN"
    MARKET_TRADING = "MARKET_TRADING"


class SettlementPeriodState(str, Enum):
    DRAFT = "DRAFT"
    RECONCILING = "RECONCILING"
    CONFIRMED = "CONFIRMED"
    INVOICED = "INVOICED"
    DISPUTED = "DISPUTED"


class SubsidyPolicyScope(str, Enum):
    NATIONAL = "NATIONAL"
    LOCAL = "LOCAL"


class SubsidyPolicyLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SubsidyDeclarationState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    ARREARS = "ARREARS"


class AuditTargetType(str, Enum):
    ALARM = "ALARM"
    SETTLEMENT = "SETTLEMENT"
    DECLARATION = "DECLARATION"
    DEFECT = "DEFECT"


# ---------------------------------------------------------------------------
# Mutable entities — id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------
class Station(TypedDict, total=False):
    id: str
    name: str
    installed_capacity_kw: float
    ac_capacity_kw: float
    commissioning_date: str
    latitude: float
    longitude: float
    grid_company: str
    feed_in_tariff_cny_per_kwh: float
    market_trading_enabled: bool
    operational_status: str
    lifecycle_state: str
    created_at: str
    updated_at: str
    version: int


class Array(TypedDict, total=False):
    id: str
    station_id: str
    code: str
    tilt_angle_deg: float
    azimuth_deg: float
    string_count: int
    created_at: str
    updated_at: str
    version: int


class PVString(TypedDict, total=False):
    id: str
    array_id: str
    code: str
    module_count: int
    combiner_box_id: Optional[str]
    inverter_id: str
    rated_dc_power_kw: float
    created_at: str
    updated_at: str
    version: int


class Module(TypedDict, total=False):
    id: str
    string_id: str
    serial_no: str
    wp_rating: float
    manufacturer: str
    warranty_supplier_id: str
    warranty_until: str
    lifecycle_state: str
    created_at: str
    updated_at: str
    version: int


class Inverter(TypedDict, total=False):
    id: str
    station_id: str
    array_id: Optional[str]
    role: str
    model: str
    vendor: str
    serial_no: str
    rated_ac_power_kw: float
    warranty_supplier_id: str
    warranty_until: str
    lifecycle_state: str
    created_at: str
    updated_at: str
    version: int


class Transformer(TypedDict, total=False):
    id: str
    station_id: str
    code: str
    rated_capacity_kva: float
    primary_voltage_kv: float
    secondary_voltage_kv: float
    grid_connection_point_no: str
    warranty_supplier_id: str
    warranty_until: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    name: str
    contact: str
    rating: str
    lifecycle_state: str
    created_at: str
    updated_at: str
    version: int


class SparePart(TypedDict, total=False):
    id: str
    sku: str
    name: str
    stock_on_hand: int
    reserved_qty: int
    unit_cost_cny: float
    created_at: str
    updated_at: str
    version: int


class AlarmEvent(TypedDict, total=False):
    id: str
    inverter_id: str
    station_id: str
    vendor_code: str
    canonical_code: str
    severity: str
    first_seen_at: str
    last_seen_at: str
    occurrence_count: int
    state: str
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[str]
    defect_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatrolPlan(TypedDict, total=False):
    id: str
    station_id: str
    name: str
    zone_route: List[str]
    kind: str
    cadence_days: Optional[int]
    checklist: Any
    lifecycle_state: str
    created_at: str
    updated_at: str
    version: int


class PatrolRecord(TypedDict, total=False):
    id: str
    patrol_plan_id: str
    station_id: str
    scheduled_for: str
    actor_id: Optional[str]
    zone_progress: List[Any]
    completed_zone_count: int
    state: str
    verification_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Defect(TypedDict, total=False):
    id: str
    station_id: str
    subject_type: str
    subject_id: str
    source: str
    source_ref_id: Optional[str]
    severity: str
    parent_defect_id: Optional[str]
    state: str
    opened_at: Optional[str]
    resolved_at: Optional[str]
    recurrence_index: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    defect_id: str
    assigned_supplier_id: str
    assigned_technician_id: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    before_metrics: Any
    after_metrics: Any
    spare_part_lines: List[Any]
    state: str
    created_at: str
    updated_at: str
    version: int


class SettlementPeriod(TypedDict, total=False):
    id: str
    station_id: str
    period_start: str
    period_end: str
    provisional_revenue_cny: Optional[float]
    final_revenue_cny: Optional[float]
    grid_company_confirmed_kwh: Optional[float]
    state: str
    invoice_no: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvestorShare(TypedDict, total=False):
    id: str
    station_id: str
    investor_name: str
    share_basis_points: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubsidyPolicy(TypedDict, total=False):
    id: str
    code: str
    scope: str
    rate_cny_per_kwh: float
    eligible_from: str
    eligible_to: str
    min_commissioning_date: Optional[str]
    max_commissioning_date: Optional[str]
    required_documents: List[str]
    lifecycle_state: str
    created_at: str
    updated_at: str
    version: int


class SubsidyDeclaration(TypedDict, total=False):
    id: str
    station_id: str
    subsidy_policy_id: str
    settlement_period_id: str
    documents: List[Any]
    claimed_kwh: Optional[float]
    subsidy_amount_cny: Optional[float]
    state: str
    approval_due_date: Optional[str]
    received_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at only (PRD §2.4)
# ---------------------------------------------------------------------------
class GenerationReading(TypedDict, total=False):
    id: str
    station_id: str
    timestamp: str
    dc_power_kw: float
    ac_power_kw: float
    irradiance_w_m2: float
    module_temp_c: float
    granularity: str
    created_at: str


class AlarmCodeMap(TypedDict, total=False):
    id: str
    vendor: str
    model: str
    vendor_code: str
    canonical_code: str
    severity: str
    root_cause_hint: str
    created_at: str


class MeteringRecord(TypedDict, total=False):
    id: str
    station_id: str
    settlement_period_id: str
    window_start: str
    window_end: str
    on_grid_kwh: float
    pricing_channel: str
    market_price_cny_per_kwh: Optional[float]
    created_at: str


class RevenueDistribution(TypedDict, total=False):
    id: str
    settlement_period_id: str
    investor_share_id: str
    investor_name: str
    share_basis_points: int
    amount_cny: float
    created_at: str


class AuditEntry(TypedDict, total=False):
    id: str
    actor_id: str
    actor_role: str
    target_type: str
    target_id: str
    action: str
    before_value: Any
    after_value: Any
    created_at: str


__all__ = [
    "UserRole",
    "StationOperationalStatus",
    "StationLifecycleState",
    "ModuleLifecycleState",
    "InverterRole",
    "InverterLifecycleState",
    "SupplierRating",
    "SupplierLifecycleState",
    "GenerationGranularity",
    "AlarmSeverity",
    "AlarmState",
    "PatrolKind",
    "PatrolPlanLifecycleState",
    "PatrolRecordState",
    "DefectSubjectType",
    "DefectSource",
    "DefectSeverity",
    "DefectState",
    "WorkOrderState",
    "PricingChannel",
    "SettlementPeriodState",
    "SubsidyPolicyScope",
    "SubsidyPolicyLifecycleState",
    "SubsidyDeclarationState",
    "AuditTargetType",
    "Station",
    "Array",
    "PVString",
    "Module",
    "Inverter",
    "Transformer",
    "Supplier",
    "SparePart",
    "AlarmEvent",
    "PatrolPlan",
    "PatrolRecord",
    "Defect",
    "WorkOrder",
    "SettlementPeriod",
    "InvestorShare",
    "SubsidyPolicy",
    "SubsidyDeclaration",
    "GenerationReading",
    "AlarmCodeMap",
    "MeteringRecord",
    "RevenueDistribution",
    "AuditEntry",
]
