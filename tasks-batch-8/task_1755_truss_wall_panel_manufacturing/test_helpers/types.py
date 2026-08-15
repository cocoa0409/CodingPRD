"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource descriptions: every primary resource carries
id/created_at/updated_at/version, except JigSetup which is immutable after
creation and carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    DESIGN_ENGINEER = "DesignEngineer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    INVENTORY_MANAGER = "InventoryManager"
    SHOP_FLOOR_LEAD = "ShopFloorLead"
    SHIPPING_COORDINATOR = "ShippingCoordinator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CUSTOMER_CONTACT = "CustomerContact"


class Posture(str, Enum):
    GREEN = "GREEN"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"


class JobStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPING = "SHIPPING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SEAL_REQUESTED = "SEAL_REQUESTED"
    SEALED = "SEALED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class CutListStatus(str, Enum):
    EXPLODED = "EXPLODED"
    RELEASED = "RELEASED"
    RECONCILING = "RECONCILING"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class CutListLineStatus(str, Enum):
    PENDING = "PENDING"
    CUT = "CUT"
    SCRAPPED = "SCRAPPED"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class CraneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CraneSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CUTTING = "CUTTING"
    ASSEMBLY = "ASSEMBLY"
    BUILT = "BUILT"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    REWORK = "REWORK"
    STAGED = "STAGED"
    LOADED = "LOADED"
    CANCELLED = "CANCELLED"


class LoadStatus(str, Enum):
    PLANNED = "PLANNED"
    STAGED = "STAGED"
    LOADING = "LOADING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    RESCHEDULED = "RESCHEDULED"
    CLAIM_HOLD = "CLAIM_HOLD"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BundleStatus(str, Enum):
    PACKED = "PACKED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    DAMAGED = "DAMAGED"
    SUPERSEDED = "SUPERSEDED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    TRIAGED = "TRIAGED"
    APPROVED_REBUILD = "APPROVED_REBUILD"
    APPROVED_CREDIT = "APPROVED_CREDIT"
    REBUILD_IN_PROGRESS = "REBUILD_IN_PROGRESS"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ChangeOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IMPACT_ASSESSED = "IMPACT_ASSESSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    APPLIED = "APPLIED"


class CustomerAccount(TypedDict, total=False):
    id: str
    company_name: str
    credit_limit_cents: int
    credit_hold: bool
    credit_used_cents: int
    storage_free_days: int
    storage_daily_fee_cents: int
    storage_fee_cap_cents: int
    max_drops_per_day: int
    delivery_terms: str
    created_at: str
    updated_at: str
    version: int


class Engineer(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    license_state: str
    license_expiry: str
    seal_authority: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    customer_id: str
    job_name: str
    jobsite_address: str
    jobsite_state: str
    delivery_window_start: str
    delivery_window_end: str
    crane_required_at_jobsite: bool
    contracted_value_cents: int
    invoiced_cents: int
    credit_issued_cents: int
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComponentDesign(TypedDict, total=False):
    id: str
    job_id: str
    component_ref: str
    revision_no: int
    supersedes_design_id: Optional[str]
    component_type: str
    span_ft: float
    pitch_degrees: float
    design_load_psf: float
    lumber_grade: str
    plating: str
    quantity_required: int
    est_board_feet_per_unit: float
    status: str
    submitted_by_engineer_id: Optional[str]
    sealed_by_engineer_id: Optional[str]
    sealed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CutList(TypedDict, total=False):
    id: str
    design_id: str
    job_id: str
    jig_setup_id: str
    rebuild_for_claim_id: Optional[str]
    total_board_feet: float
    total_pieces: int
    total_plates: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CutListLine(TypedDict, total=False):
    id: str
    cut_list_id: str
    member_label: str
    dimension: str
    length_ft: float
    qty: int
    line_board_feet: float
    waste_pct: float
    required_board_feet: float
    status: str
    created_at: str
    updated_at: str
    version: int


class JigSetup(TypedDict, total=False):
    """Immutable after creation: carries only id and created_at (no updated_at, no version)."""
    id: str
    setup_code: str
    component_type_supported: str
    plate_class: str
    changeover_minutes_from: dict
    created_at: str


class InventoryLot(TypedDict, total=False):
    id: str
    lot_kind: str
    lumber_dimension: Optional[str]
    lumber_grade: Optional[str]
    plate_class: Optional[str]
    received_board_feet: float
    received_plates: int
    unit_cost_cents_per_bf: int
    unit_cost_cents_per_plate: int
    available_bf: float
    reserved_bf: float
    consumed_bf: float
    scrapped_bf: float
    available_plates: int
    reserved_plates: int
    consumed_plates: int
    scrapped_plates: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialReservation(TypedDict, total=False):
    id: str
    lot_id: str
    cut_list_line_id: Optional[str]
    cut_list_id: Optional[str]
    reserved_bf: float
    reserved_plates: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CraneResource(TypedDict, total=False):
    id: str
    crane_code: str
    capacity_lbs: int
    crane_class: str
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CraneSlot(TypedDict, total=False):
    id: str
    crane_id: str
    purpose: str
    production_batch_id: Optional[str]
    delivery_load_id: Optional[str]
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    job_id: str
    cut_list_id: str
    jig_setup_id: str
    requested_completion_at: str
    build_sequence_no: int
    is_rebuild: bool
    source_claim_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryLoad(TypedDict, total=False):
    id: str
    job_id: str
    scheduled_date: str
    planned_weight_est_lbs: float
    provisional_freight_cents: int
    final_freight_cents: Optional[int]
    actual_total_weight_lbs: float
    crane_hours_actual: Optional[float]
    staged_at: Optional[str]
    last_dispatched_at: Optional[str]
    storage_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bundle(TypedDict, total=False):
    id: str
    delivery_load_id: str
    production_batch_id: str
    stack_position: int
    weight_lbs: float
    split_from_bundle_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    delivery_load_id: str
    bundle_id: str
    filed_by_customer_id: str
    claim_type: str
    description: str
    claimed_amount_cents: int
    damage_pct: Optional[float]
    approved_cap_cents: Optional[int]
    rebuild_material_cents: Optional[int]
    rebuild_labor_cents: Optional[int]
    redelivery_cents: Optional[int]
    residual_credit_cents: Optional[int]
    triaged_by: Optional[str]
    decided_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignChangeOrder(TypedDict, total=False):
    id: str
    job_id: str
    supersedes_design_id: str
    new_design_id: Optional[str]
    reason: str
    requested_by: str
    impact_lines_scrapped: Optional[int]
    impact_open_reservations: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
