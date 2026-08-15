"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    MERCHANDISER = "Merchandiser"
    MATERIALS_PLANNER = "MaterialsPlanner"
    CUTTING_MANAGER = "CuttingManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    LINE_SUPERVISOR = "LineSupervisor"
    SEWING_OPERATOR = "SewingOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    PAYROLL_CLERK = "PayrollClerk"
    PLANT_MANAGER = "PlantManager"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class StyleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"


class ContentQualification(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    QUALIFIED_STRICT = "QUALIFIED_STRICT"
    QUALIFIED_COST_ONLY = "QUALIFIED_COST_ONLY"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class TargetContentClaim(str, Enum):
    NONE = "NONE"
    MADE_IN_USA = "MADE_IN_USA"


class TechPackStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MachineType(str, Enum):
    SINGLE_NEEDLE = "SINGLE_NEEDLE"
    OVERLOCK = "OVERLOCK"
    COVERSTITCH = "COVERSTITCH"
    BUTTONHOLE = "BUTTONHOLE"
    MANUAL = "MANUAL"


class FabricRollStatus(str, Enum):
    RECEIVED = "RECEIVED"
    AVAILABLE = "AVAILABLE"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    CUTTING = "CUTTING"
    SEWING = "SEWING"
    FINISHED = "FINISHED"


class TrimHoldStatus(str, Enum):
    MATERIALS_OK = "MATERIALS_OK"
    TRIM_HOLD = "TRIM_HOLD"


class QualityStatus(str, Enum):
    QC_PENDING = "QC_PENDING"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    REWORK_IN_PROGRESS = "REWORK_IN_PROGRESS"


class MarkerStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CUT = "CUT"
    CANCELLED = "CANCELLED"


class BundleStatus(str, Enum):
    TICKETED = "TICKETED"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    REWORK_HOLD = "REWORK_HOLD"
    COMPLETED = "COMPLETED"


class PreReworkStatus(str, Enum):
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PieceWorkEntryStatus(str, Enum):
    LOGGED = "LOGGED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class PayrollRunStatus(str, Enum):
    OPEN = "OPEN"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class InspectionLevel(str, Enum):
    NORMAL = "NORMAL"
    TIGHTENED = "TIGHTENED"


class AqlLevel(str, Enum):
    AQL_2_5 = "AQL_2_5"
    AQL_4_0 = "AQL_4_0"


class AuditResult(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL = "FAIL"


class QualityAuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAIL = "CLOSED_FAIL"
    REWORK_RECORDED = "REWORK_RECORDED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id/created_at/updated_at/version
# (PRD §2.4: "No entity in this system omits updated_at or version.")
# ---------------------------------------------------------------------------

class Style(TypedDict, total=False):
    id: str
    style_code: str
    description: Optional[str]
    base_size: str
    size_run: List[str]
    declared_fabric_domestic: bool
    target_content_claim: str
    status: str
    active_tech_pack_id: Optional[str]
    domestic_content_pct_cost: Optional[float]
    domestic_component_ratio: Optional[float]
    content_qualification: str
    certification_status: str
    certified_by_user_id: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class TechPack(TypedDict, total=False):
    id: str
    style_id: str
    version_no: int
    base_measurements: List[Dict[str, Any]]
    grade_rules: List[Dict[str, Any]]
    labor_cost_cents_per_unit: int
    fabric_cost_cents_per_unit: int
    status: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperationSpec(TypedDict, total=False):
    id: str
    tech_pack_id: str
    sequence_no: int
    name: str
    machine_type: str
    sam_seconds: int
    piece_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class TrimItem(TypedDict, total=False):
    id: str
    sku_code: str
    description: str
    origin_country: str
    unit_cost_cents: int
    qty_on_hand: int
    qty_reserved: int
    qty_available: int
    created_at: str
    updated_at: str
    version: int


class TrimRequirement(TypedDict, total=False):
    id: str
    tech_pack_id: str
    trim_item_id: str
    units_per_garment: int
    wastage_pct: float
    created_at: str
    updated_at: str
    version: int


class FabricRoll(TypedDict, total=False):
    id: str
    roll_code: str
    fabric_code: str
    origin_country: str
    cost_cents_per_yard: int
    received_yards: float
    usable_yards: float
    allocated_yards: float
    consumed_yards: float
    available_yards: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TrimShortage(TypedDict, total=False):
    trim_item_id: str
    required_units: int
    available_units: int
    shortage_units: int


class ProductionOrder(TypedDict, total=False):
    id: str
    style_id: str
    color: str
    size_quantities: List[Dict[str, Any]]
    tech_pack_id: Optional[str]
    total_order_qty: int
    production_status: str
    trim_hold_status: str
    quality_status: str
    made_in_usa_eligible: Optional[bool]
    trim_shortages: List[TrimShortage]
    created_at: str
    updated_at: str
    version: int


class Marker(TypedDict, total=False):
    id: str
    production_order_id: str
    fabric_roll_id: str
    marker_length_yards: float
    planned_pieces: int
    allocated_yards: float
    utilization_gross_pct: Optional[float]
    utilization_net_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bundle(TypedDict, total=False):
    id: str
    marker_id: str
    production_order_id: str
    size: str
    qty: int
    ticket_no: str
    status: str
    pre_rework_status: Optional[str]
    completed_through_seq: int
    created_at: str
    updated_at: str
    version: int


class SewingLine(TypedDict, total=False):
    id: str
    line_code: str
    station_count: int
    shift_minutes: int
    created_at: str
    updated_at: str
    version: int


class LineAssignment(TypedDict, total=False):
    id: str
    sewing_line_id: str
    production_order_id: str
    operation_spec_id: str
    operator_id: str
    shift_date: str
    start_minute: int
    end_minute: int
    assigned_pieces: int
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    employee_no: str
    full_name: str
    status: str
    efficiency_pct: float
    ytd_earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class PieceWorkEntry(TypedDict, total=False):
    id: str
    bundle_id: str
    operation_spec_id: str
    operator_id: str
    work_date: str
    qty: int
    piece_earnings_cents: int
    earned_minutes: float
    payable_cents: Optional[int]
    payroll_run_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PayrollRun(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    status: str
    calculated_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    entry_count: int
    total_piece_cents: int
    total_topup_cents: int
    total_bonus_cents: int
    total_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class QualityAudit(TypedDict, total=False):
    id: str
    production_order_id: str
    re_audit_of_audit_id: Optional[str]
    inspection_level: str
    aql_level: str
    lot_size: int
    code_letter: str
    sample_size: int
    accept_max: int
    reject_min: int
    defects_found: Optional[int]
    result: str
    recorded_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
