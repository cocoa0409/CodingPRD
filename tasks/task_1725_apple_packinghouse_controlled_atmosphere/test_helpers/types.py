"""Domain types: entity TypedDicts, status enums, role enum.

Primary resources carry id + created_at + updated_at + version (PRD: common
resource properties). The disorder inspection is the single append-only
exception: it carries only id + created_at, so its TypedDict omits
updated_at and version.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ADMIN = "Admin"
    RECEIVING_CLERK = "ReceivingClerk"
    STORAGE_OPERATOR = "StorageOperator"
    PACKING_SUPERVISOR = "PackingSupervisor"
    POOL_MANAGER = "PoolManager"
    GROWER = "Grower"


class Variety(str, Enum):
    HONEYCRISP = "HONEYCRISP"
    GALA = "GALA"
    FUJI = "FUJI"
    GRANNY_SMITH = "GRANNY_SMITH"
    COSMIC_CRISP = "COSMIC_CRISP"


class GradeClass(str, Enum):
    EXTRA_FANCY = "EXTRA_FANCY"
    FANCY = "FANCY"
    UTILITY = "UTILITY"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class PackStyle(str, Enum):
    TRAY = "TRAY"
    BAG = "BAG"
    POUCH = "POUCH"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PRESIZED = "PRESIZED"
    IN_STORAGE = "IN_STORAGE"
    RELEASED = "RELEASED"
    PACKED = "PACKED"
    CLOSED = "CLOSED"
    DIVERTED = "DIVERTED"


class CARoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FILLING = "FILLING"
    SEALED = "SEALED"
    OPENED = "OPENED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    MANUAL = "MANUAL"
    SELECTED = "SELECTED"
    DIVERSION = "DIVERSION"


class SpecStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class SettlementStatus(str, Enum):
    ACCRUING = "ACCRUING"
    ADVANCE_PAID = "ADVANCE_PAID"
    SETTLED = "SETTLED"


class Grower(TypedDict, total=False):
    id: str
    name: str
    grower_code: str
    created_at: str
    updated_at: str
    version: int


class OrchardBlock(TypedDict, total=False):
    id: str
    grower_id: str
    orchard_name: str
    block_code: str
    variety: str
    storage_life_days: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    grower_id: str
    block_id: str
    received_bin_count: int
    received_weight_lbs: float
    avg_color_pct: float
    received_at: str
    size_small_lbs: float
    size_medium_lbs: float
    size_large_lbs: float
    presize_cull_lbs: float
    est_packout_pct: Optional[float]
    actual_packout_pct: Optional[float]
    diverted_weight_lbs: float
    weight_balance_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CARoom(TypedDict, total=False):
    id: str
    room_code: str
    bin_capacity: int
    o2_setpoint_pct: float
    current_o2_pct: float
    atmosphere_alarm: bool
    o2_excursion_count: int
    disorder_index: float
    priority_release: bool
    sealed_at: Optional[str]
    planned_open_date: Optional[str]
    actual_opened_at: Optional[str]
    must_empty_by: Optional[str]
    bins_allocated: int
    bins_free: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageAllocation(TypedDict, total=False):
    id: str
    room_id: str
    lot_id: str
    bins: int
    allocated_at: str
    must_release_by: str
    release_priority_score: float
    status: str
    released_at: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisorderInspection(TypedDict, total=False):
    # Append-only event record: carries ONLY id + created_at as common fields.
    id: str
    created_at: str
    room_id: str
    inspected_at: str
    scald_pct: float
    bitter_pit_pct: float
    decay_pct: float
    disorder_index: float


class PackagingSpec(TypedDict, total=False):
    id: str
    customer_name: str
    label_code: str
    grade_min: str
    color_min_pct: int
    size_class: str
    pack_style: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PackingRun(TypedDict, total=False):
    id: str
    lot_id: str
    spec_id: str
    pool_id: str
    line_code: str
    scheduled_start: str
    scheduled_end: str
    input_weight_lbs: float
    cartons_produced: Optional[int]
    packed_weight_lbs: Optional[float]
    cull_weight_lbs: Optional[float]
    juice_weight_lbs: Optional[float]
    packout_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Pool(TypedDict, total=False):
    id: str
    variety: str
    grade_class: str
    season: str
    total_packed_cartons: int
    total_sales_cents: int
    total_sale_deductions_cents: int
    total_deductions_cents: int
    estimated_price_cents: int
    pool_price_per_carton_cents: Optional[int]
    rounding_drift_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrowerSettlement(TypedDict, total=False):
    id: str
    grower_id: str
    pool_id: str
    attributed_cartons: int
    advance_amount_cents: int
    final_payment_cents: int
    paid_final_cents: int
    clawback_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
