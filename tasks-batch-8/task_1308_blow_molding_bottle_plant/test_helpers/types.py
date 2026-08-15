"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the four system-managed properties (id, created_at,
updated_at, version) described in PRD section 2.5.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LogisticsMode(str, Enum):
    WAREHOUSE = "WAREHOUSE"
    BLOW_ON_SITE = "BLOW_ON_SITE"


class FreightRateCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BottleSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_QUALIFICATION = "IN_QUALIFICATION"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    QUALIFIED = "QUALIFIED"
    PRODUCTION_ACTIVE = "PRODUCTION_ACTIVE"
    RETIRED = "RETIRED"


class ResinType(str, Enum):
    PET = "PET"
    HDPE = "HDPE"
    PP = "PP"


class ColorContrastClass(str, Enum):
    CLEAR = "CLEAR"
    LIGHT = "LIGHT"
    DARK = "DARK"


class LabelType(str, Enum):
    NONE = "NONE"
    PRESSURE_SENSITIVE = "PRESSURE_SENSITIVE"
    SHRINK_SLEEVE = "SHRINK_SLEEVE"
    IN_MOLD = "IN_MOLD"


class QualificationRunStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    CUSTOMER_REVIEW = "CUSTOMER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_MORE_DATA = "REQUEST_MORE_DATA"


class MoldStatus(str, Enum):
    STORAGE = "STORAGE"
    INSTALLED = "INSTALLED"


class BlockoutReason(str, Enum):
    DAMAGE = "DAMAGE"
    CONTAMINATION_HOLD = "CONTAMINATION_HOLD"
    PREVENTIVE = "PREVENTIVE"
    QUALITY_HOLD = "QUALITY_HOLD"


class CavityBlockoutStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"


class MachineLineStatus(str, Enum):
    IDLE = "IDLE"
    CHANGEOVER = "CHANGEOVER"
    RUNNING = "RUNNING"


class ScheduleSlotStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MaterialType(str, Enum):
    RESIN = "RESIN"
    COLORANT = "COLORANT"


class MaterialLotStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    IN_USE = "IN_USE"
    DEPLETED = "DEPLETED"
    REJECTED = "REJECTED"


class ProductionOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    RUNNING = "RUNNING"
    HELD = "HELD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProductionRunStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class QualityTestLotStatus(str, Enum):
    PENDING = "PENDING"
    SAMPLED = "SAMPLED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SCRAPPED = "SCRAPPED"
    VOIDED = "VOIDED"


class ShipmentMode(str, Enum):
    FINISHED_BOTTLES = "FINISHED_BOTTLES"
    PREFORMS = "PREFORMS"


class ShipmentStatus(str, Enum):
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    LOADING = "LOADING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DockAppointmentStatus(str, Enum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    PROCESS_ENGINEER = "ProcessEngineer"
    QUALITY_TECHNICIAN = "QualityTechnician"
    PRODUCTION_SCHEDULER = "ProductionScheduler"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    CUSTOMER_QUALITY_REP = "CustomerQualityRep"


class Customer(TypedDict, total=False):
    id: str
    name: str
    customer_code: str
    credit_limit_cents: int
    default_logistics_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FreightRateCard(TypedDict, total=False):
    id: str
    lane_code: str
    tiers: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class BottleSpec(TypedDict, total=False):
    id: str
    customer_id: str
    spec_code: str
    resin_type: str
    color_contrast_class: str
    target_weight_g: float
    weight_tolerance_pct: float
    neck_finish: str
    height_mm: float
    diameter_mm: float
    bottle_cube_cm3: int
    preform_cube_cm3: int
    preform_weight_g: float
    unit_price_cents: int
    label_type: str
    min_cavitation_required: int
    requires_inline_labeler: bool
    content_revision: int
    qualified_revision: Optional[int]
    rejected_revision: Optional[int]
    qualification_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QualificationRun(TypedDict, total=False):
    id: str
    bottle_spec_id: str
    round_no: int
    spec_revision_pinned: int
    sample_cavity_count: int
    measured_mean_weight_g: float
    weight_spread_g: float
    visual_defects: int
    weight_within_tolerance: bool
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Mold(TypedDict, total=False):
    id: str
    mold_code: str
    base_cavities: int
    compatible_resins: List[str]
    reference_weight_g: float
    installed_line_id: Optional[str]
    effective_cavities: int
    active_blockout_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CavityBlockout(TypedDict, total=False):
    id: str
    mold_id: str
    cavity_index: int
    reason: str
    blocked_at: str
    cleared_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MachineLine(TypedDict, total=False):
    id: str
    line_code: str
    has_inline_labeler: bool
    max_bottle_diameter_mm: float
    resident_volume_kg: float
    last_color_class: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleSlot(TypedDict, total=False):
    id: str
    machine_line_id: str
    production_order_id: str
    mold_id: Optional[str]
    planned_start: str
    planned_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict, total=False):
    id: str
    material_type: str
    resin_type: Optional[str]
    color_code: Optional[str]
    lot_code: str
    received_kg: float
    available_kg: float
    consumed_kg: float
    purge_wasted_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict, total=False):
    id: str
    bottle_spec_id: str
    customer_id: str
    logistics_mode: str
    quantity_ordered: int
    planned_weight_g: float
    spec_revision_baseline: int
    quantity_produced: int
    quantity_good: int
    quantity_scrapped: int
    quantity_accepted: int
    quantity_qc_scrapped: int
    quantity_open_qc: int
    quantity_reserved: int
    quantity_shipped: int
    quantity_unallocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    production_order_id: str
    machine_line_id: str
    mold_id: str
    material_lot_id: str
    colorant_lot_id: Optional[str]
    cavities_active_at_start: int
    started_at: str
    ended_at: Optional[str]
    cycles_completed: int
    good_count: int
    scrap_count: int
    actual_drawdown_kg: float
    provisional_consumption_kg: float
    consumption_variance_pct: float
    variance_alert: bool
    purge_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityTestLot(TypedDict, total=False):
    id: str
    production_run_id: str
    lot_size: int
    sample_size_n: int
    accept_number_leak: int
    accept_number_drop: int
    leak_failures: Optional[int]
    drop_failures: Optional[int]
    retest_count: int
    recorded_by_user_id: Optional[str]
    dispositioned_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    production_order_id: str
    customer_id: str
    shipment_mode: str
    quantity: int
    pallets: int
    volume_cm3: int
    dim_weight_kg: float
    actual_weight_kg: float
    chargeable_weight_kg: float
    freight_cost_cents: int
    booked_appointment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DockAppointment(TypedDict, total=False):
    id: str
    shipment_id: str
    dock_door: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
