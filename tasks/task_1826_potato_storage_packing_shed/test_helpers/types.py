"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class Variety(str, Enum):
    RUSSET_BURBANK = "RUSSET_BURBANK"
    RUSSET_NORKOTAH = "RUSSET_NORKOTAH"
    RANGER_RUSSET = "RANGER_RUSSET"
    YUKON_GOLD = "YUKON_GOLD"
    RED_LASODA = "RED_LASODA"


class ShedPosture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    QUARANTINED = "QUARANTINED"


class StorageStatus(str, Enum):
    INTAKE = "INTAKE"
    BINNED = "BINNED"
    CLOSED = "CLOSED"


class QualityStatus(str, Enum):
    CLEAR = "CLEAR"
    ON_HOLD = "ON_HOLD"
    CONDEMNED = "CONDEMNED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    SHORTFALLED = "SHORTFALLED"


class OrderType(str, Enum):
    CONTRACT = "CONTRACT"
    OPEN_MARKET = "OPEN_MARKET"


class AllocationPolicy(str, Enum):
    LOT_ASSESSMENT = "LOT_ASSESSMENT"
    SHED_BLEND = "SHED_BLEND"


class PackOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    PACKING = "PACKING"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class PackRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class WashResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AuditStatus(str, Enum):
    FIELD_WORK = "FIELD_WORK"
    PASSED = "PASSED"
    FAILED = "FAILED"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    SUPERSEDED = "SUPERSEDED"


class CullChannel(str, Enum):
    PROCESSING = "PROCESSING"
    WASTE = "WASTE"


class DiversionChannel(str, Enum):
    PROCESSING_CREDIT = "PROCESSING_CREDIT"
    WASTE = "WASTE"


class UserRole(str, Enum):
    SHED_ADMIN = "ShedAdmin"
    INTAKE_CLERK = "IntakeClerk"
    STORAGE_MANAGER = "StorageManager"
    QUALITY_ASSURANCE_MANAGER = "QualityAssuranceManager"
    SALES_MANAGER = "SalesManager"
    PACK_LINE_SUPERVISOR = "PackLineSupervisor"
    SETTLEMENT_CLERK = "SettlementClerk"
    GROWER = "Grower"


# --- Entity envelopes (primary resources carry id/created_at/updated_at/version) ---


class Grower(TypedDict, total=False):
    id: str
    name: str
    grower_code: str
    region: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageShed(TypedDict, total=False):
    id: str
    name: str
    posture: str
    consecutive_wash_failures: int
    wash_quarantine_flag: bool
    audit_failed_flag: bool
    created_at: str
    updated_at: str
    version: int


class StorageBin(TypedDict, total=False):
    id: str
    shed_id: str
    bin_code: str
    capacity_cwt: float
    variety_lock: Optional[str]
    occupied_cwt: float
    created_at: str
    updated_at: str
    version: int


class FieldLot(TypedDict, total=False):
    id: str
    grower_id: str
    bin_id: Optional[str]
    variety: str
    harvest_date: str
    original_weight_cwt: float
    shrink_cwt: float
    packed_total_cwt: float
    cull_total_cwt: float
    condemned_cwt: float
    processing_credit_cwt: float
    available_cwt: float
    reserved_cwt: float
    storage_status: str
    quality_status: str
    binned_at: Optional[str]
    closed_at: Optional[str]
    last_inhibitor_applied_at: Optional[str]
    inhibitor_application_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only (immutable) record: carries ONLY id + created_at (PRD §2.4)
class GradeOutAssessment(TypedDict, total=False):
    id: str
    field_lot_id: str
    assessment_date: str
    us1_pct: float
    us2_pct: float
    cull_pct: float
    cumulative_shrink_cwt: float
    packable_fraction: float
    created_at: str


class CustomerContract(TypedDict, total=False):
    id: str
    buyer_name: str
    variety: str
    committed_volume_cwt: float
    price_cents_per_cwt: int
    grade_min_us1_pct: float
    delivery_window_start: str
    delivery_window_end: str
    priority_rank: int
    remaining_committed_cwt: float
    allocated_active_cwt: float
    packed_to_date_cwt: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    field_lot_id: str
    raw_cwt: float
    packed_equiv_cwt: float


class PackOrder(TypedDict, total=False):
    id: str
    order_type: str
    contract_id: Optional[str]
    shed_id: str
    variety: str
    pack_unit_weight_lbs: float
    grade_min_us1_pct: float
    requested_packed_cwt: float
    allocation_policy: str
    market_price_cents_per_cwt: Optional[int]
    packed_to_date_cwt: float
    reservations: List[Reservation]
    status: str
    created_at: str
    updated_at: str
    version: int


class PackRun(TypedDict, total=False):
    id: str
    pack_order_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    packed_total_cwt: float
    cull_total_cwt: float
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (immutable) record: carries ONLY id + created_at (PRD §2.4)
class PackRunLotDraw(TypedDict, total=False):
    id: str
    pack_run_id: str
    field_lot_id: str
    raw_drawn_cwt: float
    packed_cwt: float
    us1_cwt: float
    us2_cwt: float
    cull_cwt: float
    cull_channel: str
    created_at: str


# Append-only (immutable) record: carries ONLY id + created_at (PRD §2.4)
class WashWaterCheck(TypedDict, total=False):
    id: str
    shed_id: str
    measured_at: str
    turbidity_ntu: float
    chlorine_ppm: float
    water_temp_f: float
    result: str
    created_at: str


class FoodSafetyAudit(TypedDict, total=False):
    id: str
    shed_id: str
    field_work_date: str
    status: str
    outcome: Optional[str]
    critical_findings: Optional[int]
    minor_findings: Optional[int]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrowerSettlement(TypedDict, total=False):
    id: str
    grower_id: str
    season_label: str
    status: str
    packed_cwt_basis: float
    pool_price_cents: float
    gross_cents: float
    storage_fees_cents: float
    inhibitor_fees_cents: float
    processing_credits_cents: float
    net_payable_cents: float
    finalized_by_clerk_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
