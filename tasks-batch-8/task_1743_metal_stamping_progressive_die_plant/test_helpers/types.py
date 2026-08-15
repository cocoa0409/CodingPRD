"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    PROCESS_ENGINEER = "ProcessEngineer"
    TOOLROOM_MANAGER = "ToolroomManager"
    SETUP_LEAD = "SetupLead"
    PRODUCTION_PLANNER = "ProductionPlanner"
    PRESS_OPERATOR = "PressOperator"
    QUALITY_ENGINEER = "QualityEngineer"
    SHIPPING_CLERK = "ShippingClerk"
    COST_ANALYST = "CostAnalyst"


class SteelIndex(str, Enum):
    CRU_HRC = "CRU_HRC"
    CRU_CRC = "CRU_CRC"
    LME_STEEL_SCRAP = "LME_STEEL_SCRAP"


class DieType(str, Enum):
    PROGRESSIVE = "PROGRESSIVE"
    TRANSFER = "TRANSFER"


class DieStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_REPAIR = "IN_REPAIR"
    RETIRED = "RETIRED"


class PressStatus(str, Enum):
    IDLE = "IDLE"
    IN_SETUP = "IN_SETUP"
    RUNNING = "RUNNING"


class CoilStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPROVED = "APPROVED"
    ON_HOLD = "ON_HOLD"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class LayoutStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ChangeoverStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class SensorCode(str, Enum):
    MISFEED = "MISFEED"
    SHORT_FEED = "SHORT_FEED"
    PART_EJECT_FAIL = "PART_EJECT_FAIL"
    DOUBLE_BLANK = "DOUBLE_BLANK"
    SLUG_DETECT = "SLUG_DETECT"


class OutsideProcessingStatus(str, Enum):
    SENT = "SENT"
    PARTIAL_RETURN = "PARTIAL_RETURN"
    CLOSED = "CLOSED"


class OperationType(str, Enum):
    PLATING = "PLATING"
    HEAT_TREAT = "HEAT_TREAT"
    E_COAT = "E_COAT"
    DEBURR = "DEBURR"


class PpapStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AuditResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class PricingVariant(str, Enum):
    RELEASE_LOCKED = "RELEASE_LOCKED"
    SHIPMENT_SPOT = "SHIPMENT_SPOT"


# --- Primary resources: carry id + created_at + updated_at + version (PRD §2.4) ---


class Customer(TypedDict, total=False):
    id: str
    name: str
    customer_code: str
    steel_index_basis: str
    base_index_value: float
    pass_through_pct: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    customer_id: str
    part_number: str
    material_spec: str
    thickness_mm: float
    net_weight_kg: float
    base_piece_price_cents: int
    ppap_required_level: int
    steel_content_kg: float
    created_at: str
    updated_at: str
    version: int


class Die(TypedDict, total=False):
    id: str
    die_code: str
    die_type: str
    total_stations: int
    rated_tonnage: int
    min_bed_width_mm: int
    status: str
    total_shots_lifetime: int
    shots_since_repair: int
    repair_threshold_shots: int
    created_at: str
    updated_at: str
    version: int


class Press(TypedDict, total=False):
    id: str
    press_code: str
    tonnage: int
    bed_width_mm: int
    strokes_per_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartDieAssignment(TypedDict, total=False):
    id: str
    part_id: str
    die_id: str
    qualified: bool
    created_at: str
    updated_at: str
    version: int


class SteelCoil(TypedDict, total=False):
    id: str
    coil_number: str
    heat_lot_number: str
    material_spec: str
    thickness_mm: float
    received_weight_kg: float
    remaining_weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StripLayout(TypedDict, total=False):
    id: str
    part_id: str
    revision: str
    strip_width_mm: float
    pitch_mm: float
    parts_per_strip_segment: int
    gross_weight_per_part_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict, total=False):
    id: str
    part_id: str
    quantity_ordered: int
    due_date: str
    status: str
    quantity_produced_good: int
    quantity_scrapped: int
    steel_index_at_release: float
    pricing_variant: str
    created_at: str
    updated_at: str
    version: int


class DieChangeEvent(TypedDict, total=False):
    id: str
    press_id: str
    from_die_id: Optional[str]
    to_die_id: str
    planned_start: str
    planned_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    smed_target_minutes: int
    status: str
    variance_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    production_order_id: str
    press_id: str
    die_id: str
    coil_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    shots_recorded: int
    good_count: int
    reject_count: int
    steel_consumed_kg: float
    created_at: str
    updated_at: str
    version: int


class OutsideProcessingOrder(TypedDict, total=False):
    id: str
    production_order_id: str
    operation_type: str
    quantity_sent: int
    quantity_returned_good: int
    quantity_returned_scrap: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PpapSubmission(TypedDict, total=False):
    id: str
    part_id: str
    level: int
    submission_revision: int
    control_plan_attached: bool
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LayeredAudit(TypedDict, total=False):
    id: str
    press_id: str
    audit_tier: int
    scheduled_date: str
    executed_at: Optional[str]
    result: str
    findings_count: int
    escalated_from_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger records: ONLY id + created_at (PRD §2.4) ---


class RejectEvent(TypedDict, total=False):
    id: str
    production_run_id: str
    station_number: int
    sensor_code: str
    quantity: int
    sensed_at: str
    created_at: str
    # deliberately NO updated_at / version


class IndexPublication(TypedDict, total=False):
    id: str
    index_code: str
    published_at: str
    value_usd_per_ton: float
    created_at: str
    # deliberately NO updated_at / version


class PriceAdjustment(TypedDict, total=False):
    id: str
    production_order_id: str
    variant_applied: str
    base_index_value: float
    applied_index_value: float
    adjusted_piece_price_cents: int
    created_at: str
    # deliberately NO updated_at / version
