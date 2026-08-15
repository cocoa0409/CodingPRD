"""Domain types: entity TypedDicts, status enums, role enum.

Primary top-level resources carry id + created_at + updated_at + version.
Immutable measurement records carry only id + created_at (PRD §2.6).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SERVICE_MANAGER = "ServiceManager"
    PLANT_OPERATOR = "PlantOperator"
    TECHNICIAN = "Technician"
    SAFETY_OFFICER = "SafetyOfficer"


class FlowPosture(str, Enum):
    NORMAL = "NORMAL"
    PENDING_REPLENISHMENT = "PENDING_REPLENISHMENT"
    FLOW_IMPAIRED = "FLOW_IMPAIRED"


class SitePosture(str, Enum):
    NORMAL = "NORMAL"
    ATTENTION = "ATTENTION"
    CRITICAL = "CRITICAL"


class ScaleStatus(str, Enum):
    IN_TOLERANCE = "IN_TOLERANCE"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"


class VesselKind(str, Enum):
    SILO = "SILO"
    BIN = "BIN"
    HOPPER = "HOPPER"


class ReplenishmentPolicy(str, Enum):
    TARGET_FILL = "TARGET_FILL"
    DAYS_OF_COVER = "DAYS_OF_COVER"


class ErrorBasis(str, Enum):
    OF_READING = "OF_READING"
    OF_FULL_SCALE = "OF_FULL_SCALE"


class OrderStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class TicketStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"


class JobType(str, Enum):
    DIAGNOSIS = "DIAGNOSIS"
    CLEANOUT = "CLEANOUT"
    INSPECTION = "INSPECTION"
    RETROFIT_AERATION = "RETROFIT_AERATION"
    RETROFIT_VIBRATOR = "RETROFIT_VIBRATOR"


class CommercialTrack(str, Enum):
    CONTRACT_SERVICE = "CONTRACT_SERVICE"
    CAPITAL_PROJECT = "CAPITAL_PROJECT"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class VoidReason(str, Enum):
    NONE = "NONE"
    AUTO_QUALITY_HAZARD = "AUTO_QUALITY_HAZARD"


class FlowabilityGrade(str, Enum):
    GOOD = "GOOD"
    MARGINAL = "MARGINAL"
    POOR = "POOR"


class CalibrationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReadingSource(str, Enum):
    MANUAL = "MANUAL"
    SENSOR = "SENSOR"


class CustomerSite(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    contract_discount_pct: float
    capital_threshold_cents: int
    credit_hold: bool
    site_posture: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    name: str
    weekly_capacity_hours: float
    certifications: List[str]
    active: bool
    remaining_capacity_hours: float
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    vessel_kind: str
    capacity_tons: float
    material_name: str
    opening_inventory_tons: float
    reorder_point_pct: float
    target_fill_pct: float
    replenishment_policy: str
    cover_days: float
    default_usage_tons: float
    moisture_limit_pct: float
    error_basis: str
    full_scale_tons: Optional[float]
    current_inventory_tons: float
    flow_posture: str
    scale_status: str
    created_at: str
    updated_at: str
    version: int


class LevelReading(TypedDict, total=False):
    # Immutable measurement record: only id + created_at (no updated_at, no version)
    id: str
    vessel_id: str
    measured_at: str
    level_pct: float
    source: str
    created_at: str


class MaterialQualityReport(TypedDict, total=False):
    # Immutable measurement record: only id + created_at (no updated_at, no version)
    id: str
    vessel_id: str
    sampled_at: str
    moisture_pct: float
    caking_index: int
    flowability_grade: str
    created_at: str


class ScaleCalibration(TypedDict, total=False):
    # Immutable measurement record: only id + created_at (no updated_at, no version)
    id: str
    vessel_id: str
    tested_at: str
    test_weight_tons: float
    indicated_tons: float
    tolerance_pct: float
    error_basis_used: str
    error_pct: float
    result: str
    created_at: str


class ReplenishmentOrder(TypedDict, total=False):
    id: str
    vessel_id: str
    trigger_reading_id: str
    policy_used: str
    order_quantity_tons: float
    status: str
    delivered_tons: Optional[float]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict, total=False):
    id: str
    site_id: str
    vessel_id: str
    technician_id: Optional[str]
    source_permit_id: Optional[str]
    job_type: str
    requires_entry: bool
    est_hours: float
    crew_size: int
    description: str
    status: str
    estimate_cents: int
    commercial_track: str
    window_start: Optional[str]
    window_end: Optional[str]
    actual_hours: Optional[float]
    mileage_miles: Optional[float]
    disposal_tons: Optional[float]
    invoice_labor_cents: Optional[int]
    invoice_mobilization_cents: Optional[int]
    invoice_disposal_cents: Optional[int]
    invoice_subtotal_cents: Optional[int]
    invoice_discount_cents: Optional[int]
    invoice_tax_cents: Optional[int]
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EntryPermit(TypedDict, total=False):
    id: str
    vessel_id: str
    ticket_id: str
    entrant_technician_id: str
    issuer_user_id: Optional[str]
    window_start: str
    window_end: str
    lockout_checklist_confirmed: Optional[bool]
    atmosphere_ok: Optional[bool]
    last_oxygen_pct: Optional[float]
    last_combustible_pct: Optional[float]
    status: str
    void_reason: str
    created_at: str
    updated_at: str
    version: int
