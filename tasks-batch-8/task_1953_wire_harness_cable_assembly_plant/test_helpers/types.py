"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly. Entities whose records are append-only
evidence (crimp pull tests, electrical test records) carry only ``id`` and
``created_at`` from the common set — no ``updated_at``, no ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class WorkmanshipClass(str, Enum):
    IPC_CLASS_1 = "IPC_CLASS_1"
    IPC_CLASS_2 = "IPC_CLASS_2"
    IPC_CLASS_3 = "IPC_CLASS_3"


class DrawingStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"


class ComponentType(str, Enum):
    CONNECTOR = "CONNECTOR"
    TERMINAL = "TERMINAL"
    WIRE = "WIRE"
    SEAL = "SEAL"
    SLEEVE = "SLEEVE"


class SupplyType(str, Enum):
    FACTORY_STOCK = "FACTORY_STOCK"
    CUSTOMER_CONSIGNED = "CUSTOMER_CONSIGNED"


class ConsignedLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    RETURNED = "RETURNED"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ApplicatorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_SETUP = "IN_SETUP"
    QUALIFIED = "QUALIFIED"
    QUARANTINED = "QUARANTINED"


class ApplicatorSetupStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TerminalType(str, Enum):
    OPEN_BARREL = "OPEN_BARREL"
    CLOSED_BARREL = "CLOSED_BARREL"


class MachineProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    QUALIFIED = "QUALIFIED"
    HELD = "HELD"


class BuildOrderStatus(str, Enum):
    OPEN = "OPEN"
    KITTING = "KITTING"
    IN_BUILD = "IN_BUILD"
    TESTING = "TESTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    QC_HOLD = "QC_HOLD"


class KitStatus(str, Enum):
    PICKING = "PICKING"
    STAGED = "STAGED"
    DELIVERED_LINESIDE = "DELIVERED_LINESIDE"
    RETURNED = "RETURNED"


class HarnessUnitStatus(str, Enum):
    BUILT = "BUILT"
    TEST_PASS = "TEST_PASS"
    REWORK = "REWORK"
    SUSPECT = "SUSPECT"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"


class ScrapReason(str, Enum):
    DAMAGE = "DAMAGE"
    QC_SUSPECT = "QC_SUSPECT"
    ECN_DISPOSITION = "ECN_DISPOSITION"


class SampleKind(str, Enum):
    FIRST_ARTICLE = "FIRST_ARTICLE"
    LOT_SAMPLE = "LOT_SAMPLE"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class TestType(str, Enum):
    CONTINUITY = "CONTINUITY"
    HIPOT = "HIPOT"


class WipDisposition(str, Enum):
    REWORK = "REWORK"
    USE_AS_IS = "USE_AS_IS"
    SCRAP = "SCRAP"


class EcnStatus(str, Enum):
    OPEN = "OPEN"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    HARNESS_ENGINEER = "HarnessEngineer"
    PROCESS_ENGINEER = "ProcessEngineer"
    QUALITY_MANAGER = "QualityManager"
    QUALITY_INSPECTOR = "QualityInspector"
    PRODUCTION_PLANNER = "ProductionPlanner"
    MATERIALS_CLERK = "MaterialsClerk"
    LINE_OPERATOR = "LineOperator"
    SHIPPING_CLERK = "ShippingClerk"


class HarnessDrawing(TypedDict, total=False):
    id: str
    drawing_number: str
    customer_code: str
    revision: str
    workmanship_class: str
    status: str
    released_at: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrawingComponent(TypedDict, total=False):
    id: str
    drawing_id: str
    find_number: str
    component_type: str
    mpn: str
    qty_per_harness: int
    supply_type: str
    unit_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class ConsignedLot(TypedDict, total=False):
    id: str
    lot_code: str
    owner_customer_code: str
    mpn: str
    unit_liability_cents: int
    replacement_cost_cents: int
    qty_received: int
    qty_on_hand: int
    qty_issued_open: int
    qty_consumed: int
    qty_scrapped: int
    qty_returned: int
    book_liability_cents: int
    replacement_liability_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    operator_name: str
    badge_no: str
    created_at: str
    updated_at: str
    version: int


class OperatorCertification(TypedDict, total=False):
    id: str
    operator_id: str
    workmanship_class: str
    issued_at: str
    expires_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicator(TypedDict, total=False):
    id: str
    applicator_code: str
    compatible_terminal_mpn: str
    status: str
    current_program_id: Optional[str]
    qualified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplicatorSetup(TypedDict, total=False):
    id: str
    applicator_id: str
    program_id: str
    setup_operator_id: str
    planned_start_at: str
    planned_end_at: str
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MachineProgram(TypedDict, total=False):
    id: str
    program_code: str
    drawing_id: str
    applicator_id: str
    wire_gauge_awg: int
    wire_type: str
    cut_length_mm: float
    strip_length_mm: float
    terminal_mpn: str
    terminal_type: str
    min_pull_force_n: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildOrder(TypedDict, total=False):
    id: str
    order_code: str
    drawing_id: str
    drawing_revision_pinned: str
    workmanship_class: str
    qty_ordered: int
    material_budget_cents: Optional[int]
    material_spent_cents: int
    qty_built: int
    qty_scrapped: int
    standard_cost_cents: int
    actual_cost_cents: int
    scrap_recovery_credit_cents: int
    status: str
    qc_hold_return_status: Optional[str]
    held_by_program_id: Optional[str]
    use_as_is_flag: bool
    next_unit_seq: int
    created_at: str
    updated_at: str
    version: int


class KitIssue(TypedDict, total=False):
    component_id: str
    qty_issued: int
    source: str
    consigned_lot_id: Optional[str]
    unit_cost_snapshot_cents: int
    issued_at: str
    voided: bool


class Kit(TypedDict, total=False):
    id: str
    build_order_id: str
    kit_seq: int
    status: str
    issues: List[KitIssue]
    shortage_count: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarnessUnit(TypedDict, total=False):
    id: str
    build_order_id: str
    serial_number: str
    drawing_revision_built: str
    built_by_operator_id: str
    status: str
    rework_count: int
    continuity_pass: bool
    hipot_pass: bool
    suspect_marked_at: Optional[str]
    scrap_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only evidence record: carries ONLY id + created_at from the common set.
class CrimpPullTest(TypedDict, total=False):
    id: str
    applicator_id: str
    program_id: str
    operator_id: str
    sample_kind: str
    measured_force_n: float
    min_pull_force_n_snapshot: float
    result: str
    tested_at: str
    created_at: str


# Append-only evidence record: carries ONLY id + created_at from the common set.
class ElectricalTestRecord(TypedDict, total=False):
    id: str
    harness_unit_id: str
    test_operator_id: str
    test_type: str
    opens_count: Optional[int]
    hipot_voltage_v: Optional[float]
    dwell_seconds: Optional[float]
    measured_leakage_ua: Optional[float]
    leakage_limit_ua: Optional[float]
    result: str
    tested_at: str
    created_at: str


class EngineeringChangeNotice(TypedDict, total=False):
    id: str
    ecn_code: str
    drawing_id: str
    from_revision: str
    to_revision: str
    wip_disposition: str
    status: str
    applied_at: Optional[str]
    new_drawing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
