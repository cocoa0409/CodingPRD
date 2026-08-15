"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    CORE_INSPECTOR = "CoreInspector"
    SHOP_TECHNICIAN = "ShopTechnician"
    QUALITY_INSPECTOR = "QualityInspector"
    DISTRIBUTOR = "Distributor"
    WARRANTY_ADJUSTER = "WarrantyAdjuster"


class EmissionsTier(str, Enum):
    FEDERAL = "FEDERAL"
    CALIFORNIA = "CALIFORNIA"


class DistributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class CoreReturnStatus(str, Enum):
    RECEIVED = "RECEIVED"
    GRADED = "GRADED"
    DISPUTED = "DISPUTED"
    CLOSED = "CLOSED"


class CoreReturnGrade(str, Enum):
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    GRADE_C = "GRADE_C"
    REJECT = "REJECT"


class CoreDepositStatus(str, Enum):
    HELD = "HELD"
    CLOSED_REFUNDED = "CLOSED_REFUNDED"
    FORFEITED = "FORFEITED"


class BuildSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class WorkOrderStatus(str, Enum):
    QUEUED = "QUEUED"
    TEARDOWN = "TEARDOWN"
    MACHINING = "MACHINING"
    ASSEMBLY = "ASSEMBLY"
    DYNO_TEST = "DYNO_TEST"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class OpType(str, Enum):
    BORE = "BORE"
    DECK = "DECK"
    CRANK_GRIND = "CRANK_GRIND"


class MachineOperationStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OperationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PartType(str, Enum):
    CRANKSHAFT = "CRANKSHAFT"
    CYLINDER_HEAD = "CYLINDER_HEAD"
    ENGINE_BLOCK = "ENGINE_BLOCK"
    CAMSHAFT = "CAMSHAFT"


class ReuseGrade(str, Enum):
    REUSE_OK = "REUSE_OK"
    REWORK = "REWORK"
    SCRAP = "SCRAP"


class ComponentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    CONSUMED = "CONSUMED"
    SCRAPPED = "SCRAPPED"


class RemanEngineStatus(str, Enum):
    BUILT = "BUILT"
    DYNO_PASSED = "DYNO_PASSED"
    SEALED = "SEALED"
    SOLD = "SOLD"
    RETURNED = "RETURNED"
    SCRAPPED = "SCRAPPED"


class DynoResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class WarrantyClaimStatus(str, Enum):
    OPEN = "OPEN"
    TEARDOWN_COMPLETE = "TEARDOWN_COMPLETE"
    APPROVED_CREDIT = "APPROVED_CREDIT"
    APPROVED_REPLACEMENT = "APPROVED_REPLACEMENT"
    DENIED = "DENIED"


class WarrantyOutcome(str, Enum):
    APPROVED_CREDIT = "APPROVED_CREDIT"
    APPROVED_REPLACEMENT = "APPROVED_REPLACEMENT"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# Entity records. Every primary resource carries id/created_at/updated_at/
# version (PRD §2.4). DynoTest is the single exception: id + created_at only.
# ---------------------------------------------------------------------------

class Distributor(TypedDict):
    id: str
    distributor_code: str
    name: str
    emissions_requirement: str
    status: str
    credit_limit_cents: int
    volume_discount_pct: float
    deposits_held_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class CoreReturn(TypedDict):
    id: str
    distributor_id: str
    build_spec_id: str
    core_deposit_id: Optional[str]
    status: str
    grade: Optional[str]
    missing_components: List[str]
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    graded_at: Optional[str]
    dispute_count: int
    created_at: str
    updated_at: str
    version: int


class CoreDeposit(TypedDict):
    id: str
    distributor_id: str
    reman_engine_id: str
    amount_cents: int
    sold_at: str
    status: str
    refunded_cents: int
    forfeited_cents: int
    age_days_at_close: Optional[int]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildSpec(TypedDict):
    id: str
    engine_family: str
    application_code: str
    emissions_tier: str
    status: str
    list_price_cents: int
    core_deposit_cents: int
    core_base_credit_cents: int
    allowed_reuse_grades: List[str]
    allowed_interchange_groups: List[str]
    dyno_min_horsepower: int
    dyno_min_oil_pressure_psi: float
    dyno_max_coolant_temp_f: int
    required_op_sequence: List[str]
    created_at: str
    updated_at: str
    version: int


class RemanWorkOrder(TypedDict):
    id: str
    core_return_id: str
    build_spec_id: str
    status: str
    reman_engine_id: Optional[str]
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class MachineOperation(TypedDict):
    id: str
    work_order_id: str
    op_type: str
    sequence: int
    station_code: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    result: Optional[str]
    status: str
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict):
    id: str
    work_order_id: str
    part_type: str
    interchange_group: str
    reuse_grade: Optional[str]
    status: str
    consumed_by_work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemanEngine(TypedDict):
    id: str
    work_order_id: str
    build_spec_id: str
    serial_number: str
    status: str
    latest_dyno_result: Optional[str]
    sealed_at: Optional[str]
    sealed_by: Optional[str]
    distributor_id: Optional[str]
    sold_at: Optional[str]
    sale_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DynoTest(TypedDict):
    # Immutable record (PRD §2.4): carries ONLY id + created_at, never
    # updated_at or version.
    id: str
    reman_engine_id: str
    recorded_by: str
    dyno_cell_code: str
    started_at: str
    ended_at: str
    horsepower: int
    oil_pressure_psi: float
    coolant_temp_f: int
    result: str
    attempt: int
    created_at: str


class WarrantyClaim(TypedDict):
    id: str
    reman_engine_id: str
    distributor_id: str
    failure_description: str
    status: str
    filed_at: str
    months_in_service: int
    teardown_findings: Optional[str]
    teardown_by: Optional[str]
    settled_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
