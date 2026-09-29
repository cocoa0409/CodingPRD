"""Domain types for the Fountain Beverage Service Network API.

Every enum member and every TypedDict key below is named by the PRD.
Note that TelemetryReading carries only ``id`` and ``created_at`` — the PRD
states it is the one resource kind that does not carry ``updated_at`` or
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    SUPPLY_PLANNER = "SupplyPlanner"
    ROUTE_DRIVER = "RouteDriver"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    OUTLET_MANAGER = "OutletManager"


# ─── Status / enum vocabularies ───────────────────────────────────────────


class OutletStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ServicePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ThroughputTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class OutletStatusAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    CLOSE = "CLOSE"


class HoldAction(str, Enum):
    PLACE = "PLACE"
    RELEASE = "RELEASE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SHORTFALL_REVIEW = "SHORTFALL_REVIEW"
    RECALL_PENDING = "RECALL_PENDING"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ExposureVariant(str, Enum):
    BOOK_VALUE = "BOOK_VALUE"
    REPLACEMENT_RISK = "REPLACEMENT_RISK"


class RecallOutcome(str, Enum):
    FEE_ONLY = "FEE_ONLY"
    RECALL = "RECALL"


class DispenserUnitStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    SERVICE_HOLD = "SERVICE_HOLD"
    RECALL_STAGED = "RECALL_STAGED"
    RETURNED = "RETURNED"


class CalibrationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    IN_SPEC = "IN_SPEC"
    OUT_OF_SPEC = "OUT_OF_SPEC"


class SupplyForm(str, Enum):
    CARTRIDGE = "CARTRIDGE"
    BAG_IN_BOX = "BAG_IN_BOX"


class TelemetrySource(str, Enum):
    TELEMETRY = "TELEMETRY"
    MANUAL_AUDIT = "MANUAL_AUDIT"


class ForecastVariant(str, Enum):
    TRAILING_ACTUAL = "TRAILING_ACTUAL"
    THROUGHPUT_PROJECTED = "THROUGHPUT_PROJECTED"


class AlertLevel(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    CRITICAL = "CRITICAL"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    PENDING = "PENDING"
    ARRIVED = "ARRIVED"
    SERVED = "SERVED"
    SKIPPED = "SKIPPED"


class SkipReasonCode(str, Enum):
    OUTLET_CLOSED = "OUTLET_CLOSED"
    POSTURE_FROZEN = "POSTURE_FROZEN"
    ACCESS_DENIED = "ACCESS_DENIED"


class TaskType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    BRIX_CALIBRATION = "BRIX_CALIBRATION"
    SANITATION = "SANITATION"
    FILTER_CHANGE = "FILTER_CHANGE"


class TaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class BreachKind(str, Enum):
    DATE = "DATE"
    GALLON = "GALLON"


class CalibrationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ServiceCallStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class SymptomCode(str, Enum):
    NO_POUR = "NO_POUR"
    OFF_RATIO = "OFF_RATIO"
    LEAK = "LEAK"
    CO2_LOW = "CO2_LOW"
    ICE_FAULT = "ICE_FAULT"


class Severity(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    CRITICAL = "CRITICAL"


class ResolutionCode(str, Enum):
    PART_REPLACED = "PART_REPLACED"
    CALIBRATED = "CALIBRATED"
    CLEANED = "CLEANED"
    NO_FAULT_FOUND = "NO_FAULT_FOUND"


# ─── Entity shapes ────────────────────────────────────────────────────────


class Outlet(TypedDict):
    id: str
    name: str
    account_code: str
    region_code: str
    throughput_tier: str
    water_hardness_gpg: float
    status: str
    service_posture: str
    open_compliance_hold_count: int
    overdue_task_count: int
    last_hold_placed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlacementAgreement(TypedDict):
    id: str
    outlet_id: str
    term_start_date: str
    term_end_date: str
    annual_commitment_gallons: float
    free_on_loan: bool
    shortfall_fee_cents_per_gallon: int
    equipment_value_cents: int
    status: str
    assessed_shortfall_gallons: float
    assessed_fee_cents: int
    exposure_variant: str
    recall_exposure_cents: Optional[int]
    assessment_period_start: Optional[str]
    assessment_period_end: Optional[str]
    shortfall_assessed_by_user_id: Optional[str]
    recall_decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispenserUnit(TypedDict):
    id: str
    outlet_id: str
    agreement_id: str
    serial_number: str
    model_code: str
    installed_at: str
    status: str
    calibration_status: str
    lifetime_dispensed_gallons: float
    gallons_at_last_filter_change: float
    brix_ratio_last_measured: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict):
    id: str
    sku_code: str
    brand_name: str
    supply_form: str
    case_pack_units: int
    ounces_per_unit: float
    promotional: bool
    promo_window_start: Optional[str]
    promo_window_end: Optional[str]
    national_allocation_units: int
    reserved_pool_units: int
    created_at: str
    updated_at: str
    version: int


class TelemetryReading(TypedDict):
    """The PRD's sole immutable resource kind: no ``updated_at``, no ``version``."""

    id: str
    dispenser_unit_id: str
    supply_item_id: str
    dispensed_ounces: float
    reading_at: str
    window_days: int
    source: str
    created_at: str


class OutletSupplyPosition(TypedDict):
    id: str
    outlet_id: str
    supply_item_id: str
    on_hand_units: int
    forecast_variant: str
    forecast_units: float
    requested_units: int
    allocated_units: int
    planned_route_stop_id: Optional[str]
    alert_level: str
    promo_suppressed: bool
    alert_acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplenishmentRoute(TypedDict):
    id: str
    route_code: str
    depot_region_code: str
    service_date: str
    van_code: str
    capacity_units: int
    status: str
    committed_units: int
    delivered_units: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    outlet_id: str
    sequence_index: int
    window_start: str
    window_end: str
    status: str
    delivered_units: int
    skip_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceTask(TypedDict):
    id: str
    dispenser_unit_id: str
    task_type: str
    due_at: str
    gallon_interval: Optional[float]
    status: str
    breach_kind: Optional[str]
    effective_gallon_interval: Optional[float]
    completed_at: Optional[str]
    completed_by_user_id: Optional[str]
    measured_brix_ratio: Optional[float]
    calibration_outcome: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCall(TypedDict):
    id: str
    dispenser_unit_id: str
    reported_at: str
    symptom_code: str
    severity_score: int
    severity: str
    status: str
    van_code: Optional[str]
    scheduled_window_start: Optional[str]
    scheduled_window_end: Optional[str]
    assigned_tech_user_id: Optional[str]
    reserved_part_stock_id: Optional[str]
    reserved_part_units: int
    consumed_part_units: int
    escalation_count: int
    resolution_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VanPartStock(TypedDict):
    id: str
    van_code: str
    part_sku: str
    on_van_units: int
    reserved_units: int
    consumed_units: int
    initial_units: int
    restocked_units: int
    created_at: str
    updated_at: str
    version: int


class AllocationSummary(TypedDict):
    """Reply shape of ``POST /route-stops/{id}/allocations``."""

    route_stop_id: str
    allocated_position_count: int
    total_allocated_units: int
    granted_units_by_position: dict


class BrandMixLine(TypedDict):
    supply_item_id: str
    sku_code: str
    brand_name: str
    total_ounces: float
    share_pct: float


class BrandMixReport(TypedDict):
    outlet_id: str
    period_start: str
    period_end: str
    total_ounces: float
    lines: List[BrandMixLine]
    top_brand_name: Optional[str]
    promo_available_skus: List[str]
