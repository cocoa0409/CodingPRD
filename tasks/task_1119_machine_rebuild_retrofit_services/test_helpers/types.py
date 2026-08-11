"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    ASSESSOR = "Assessor"
    PROJECT_MANAGER = "ProjectManager"
    REBUILD_ENGINEER = "RebuildEngineer"
    QUALITY_INSPECTOR = "QualityInspector"
    TRAINER = "Trainer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
    PLATFORM_ADMIN = "PlatformAdmin"


class MachineType(str, Enum):
    LATHE = "LATHE"
    MILL = "MILL"
    GRINDER = "GRINDER"


class ControlGeneration(str, Enum):
    LEGACY = "LEGACY"
    MODERN = "MODERN"


class MachineStatus(str, Enum):
    REGISTERED = "REGISTERED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    ASSESSED = "ASSESSED"
    IN_PROJECT = "IN_PROJECT"
    RETURNED = "RETURNED"
    TRADED_IN = "TRADED_IN"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class RecommendedPath(str, Enum):
    RETROFIT_ONLY = "RETROFIT_ONLY"
    MECHANICAL_REBUILD = "MECHANICAL_REBUILD"
    FULL_REBUILD = "FULL_REBUILD"


class Decision(str, Enum):
    NONE = "NONE"
    RETROFIT_ONLY = "RETROFIT_ONLY"
    MECHANICAL_REBUILD = "MECHANICAL_REBUILD"
    FULL_REBUILD = "FULL_REBUILD"


class WorkStatus(str, Enum):
    SCOPED = "SCOPED"
    DECIDED = "DECIDED"
    PARTS_SOURCING = "PARTS_SOURCING"
    REBUILD_IN_PROGRESS = "REBUILD_IN_PROGRESS"
    AWAITING_ACCEPTANCE = "AWAITING_ACCEPTANCE"
    REWORK = "REWORK"
    ESCALATED = "ESCALATED"
    ACCEPTED = "ACCEPTED"
    TRAINING_IN_PROGRESS = "TRAINING_IN_PROGRESS"
    HANDOVER_READY = "HANDOVER_READY"
    WARRANTY_ACTIVE = "WARRANTY_ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CommercialStatus(str, Enum):
    QUOTE_DRAFT = "QUOTE_DRAFT"
    QUOTE_SENT = "QUOTE_SENT"
    APPROVED = "APPROVED"


class OemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"
    SUPERSEDED = "SUPERSEDED"


class PartLineStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    RE_PENDING = "RE_PENDING"
    RE_FULFILLED = "RE_FULFILLED"
    CANCELLED = "CANCELLED"


class ReJobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SPEC_CAPTURED = "SPEC_CAPTURED"
    PROTOTYPE_FABRICATED = "PROTOTYPE_FABRICATED"
    VALIDATED = "VALIDATED"
    CANCELLED = "CANCELLED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class StageStatus(str, Enum):
    PLANNED = "PLANNED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    INSTALLED = "INSTALLED"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class AcceptanceTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class EvaluationVariant(str, Enum):
    WORST_CASE = "WORST_CASE"
    ISO_STATISTICAL = "ISO_STATISTICAL"


class TrainingStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ClaimType(str, Enum):
    ACCURACY_DRIFT = "ACCURACY_DRIFT"
    MECHANICAL_DEFECT = "MECHANICAL_DEFECT"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class ValuationVariant(str, Enum):
    MARKET_COMPARABLE = "MARKET_COMPARABLE"
    COST_APPROACH = "COST_APPROACH"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    region: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict, total=False):
    id: str
    customer_id: str
    serial_number: str
    machine_type: str
    year_of_manufacture: int
    control_generation: str
    spindle_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    machine_id: str
    assessor_id: str
    positioning_deviation_microns: float
    spindle_runout_microns: float
    backlash_microns: float
    scope_notes: str
    wear_index: float
    recommended_path: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RebuildProject(TypedDict, total=False):
    id: str
    machine_id: str
    customer_id: str
    assessment_id: str
    decision: str
    decision_reason: Optional[str]
    assigned_engineer_id: str
    work_status: str
    commercial_status: str
    quote_revision: int
    quote_stale: bool
    base_price_cents: int
    parts_total_cents: int
    labor_cents: int
    discount_cents: int
    applied_trade_in_credit_cents: int
    quote_price_cents: int
    rework_count: int
    consecutive_fail_count: int
    rework_cost_cents: int
    escalation_count: int
    accepted_positioning_microns: Optional[float]
    delivery_date: Optional[str]
    warranty_months: Optional[int]
    warranty_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    part_number: str
    description: str
    oem_status: str
    superseded_by_id: Optional[str]
    unit_cost_cents: int
    stock_quantity: int
    available_quantity: int
    reserved_quantity: int
    lead_time_days: int
    created_at: str
    updated_at: str
    version: int


class ProjectPartLine(TypedDict, total=False):
    id: str
    project_id: str
    part_id: str
    quantity: int
    unit_price_cents: int
    obs_multiplier: float
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReverseEngineeringJob(TypedDict, total=False):
    id: str
    part_line_id: str
    project_id: str
    part_id: str
    revision_count: int
    re_cost_cents: int
    fabricated_by_id: Optional[str]
    validated_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DowntimeWindow(TypedDict, total=False):
    id: str
    customer_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShipmentStage(TypedDict, total=False):
    id: str
    project_id: str
    window_id: str
    stage_sequence: int
    planned_ship_date: str
    planned_return_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AcceptanceTest(TypedDict, total=False):
    id: str
    project_id: str
    inspector_id: str
    attempt_number: int
    samples_microns: list
    repeatability_microns: float
    evaluation_variant: str
    max_abs_sample_microns: float
    statistic_value: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    project_id: str
    trainer_id: Optional[str]
    sessions_required: int
    sessions_completed: int
    documentation_delivered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    project_id: str
    claim_type: str
    measured_positioning_microns: Optional[float]
    drift_microns: Optional[float]
    filed_at: str
    resolution_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeInOffer(TypedDict, total=False):
    id: str
    machine_id: str
    customer_id: str
    valuation_variant: str
    market_value_cents: int
    cost_value_cents: int
    residual_value_cents: int
    expires_at: str
    applied_project_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
