"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    INSPECTOR = "Inspector"
    TECHNICIAN = "Technician"
    CERTIFIER = "Certifier"
    PLANNER = "Planner"
    SERVICE_MANAGER = "ServiceManager"


class EquipmentClass(str, Enum):
    PUMP = "PUMP"
    GENERAL_VALVE = "GENERAL_VALVE"
    SAFETY_RELIEF_VALVE = "SAFETY_RELIEF_VALVE"


class TestStandard(str, Enum):
    API_610_PER_POINT = "API_610_PER_POINT"
    SHOP_WEIGHTED_AVG = "SHOP_WEIGHTED_AVG"


class RepairOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_INSPECTION = "IN_INSPECTION"
    QUOTE_IN_PROGRESS = "QUOTE_IN_PROGRESS"
    AUTHORIZED = "AUTHORIZED"
    IN_REPAIR = "IN_REPAIR"
    IN_TEST = "IN_TEST"
    READY_FOR_CERT = "READY_FOR_CERT"
    COMPLETE = "COMPLETE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FailureMode(str, Enum):
    SEAL_LEAK = "SEAL_LEAK"
    BEARING_FAILURE = "BEARING_FAILURE"
    CAVITATION = "CAVITATION"
    SEAT_LEAKAGE = "SEAT_LEAKAGE"
    SPRING_DRIFT = "SPRING_DRIFT"
    OTHER = "OTHER"


class IntakePriority(str, Enum):
    STANDARD = "STANDARD"
    SURGE = "SURGE"


class RepairOutcome(str, Enum):
    NONE = "NONE"
    FIRST_TIME_FIX = "FIRST_TIME_FIX"
    RE_REPAIR = "RE_REPAIR"


class RecommendedAction(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"
    RETURN_UNREPAIRED = "RETURN_UNREPAIRED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class PricingVariant(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    WARRANTY = "WARRANTY"


class PartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"


class PoolStatus(str, Enum):
    IN_POOL = "IN_POOL"
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    WITHDRAWN = "WITHDRAWN"


class TestType(str, Enum):
    PERFORMANCE_CURVE = "PERFORMANCE_CURVE"
    HYDROSTATIC = "HYDROSTATIC"
    POP_TEST = "POP_TEST"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SeatLeakageClass(str, Enum):
    CLASS_IV = "CLASS_IV"
    CLASS_V = "CLASS_V"
    CLASS_VI = "CLASS_VI"


class CertStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class WindowPosture(str, Enum):
    NORMAL = "NORMAL"
    SURGE = "SURGE"
    FULL = "FULL"


# All resources carry the four system-managed fields id / created_at /
# updated_at / version (PRD §2.5).

class Customer(TypedDict, total=False):
    id: str
    name: str
    account_number: str
    credit_limit_cents: int
    warranty_terms_days: int
    pool_program: bool
    pool_available_count: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    customer_id: str
    serial_number: str
    equipment_class: str
    manufacturer: str
    model: str
    rated_flow_gpm: Optional[float]
    set_pressure_psig: Optional[float]
    test_standard: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    customer_id: str
    asset_id: str
    warranty_parent_ro_id: Optional[str]
    failure_mode: str
    failure_description: str
    intake_priority: str
    planned_start_date: str
    planned_end_date: str
    estimated_bay_hours: int
    exchange_requested: bool
    status: str
    warranty_case: bool
    repeat_failure_flag: bool
    repair_round: int
    repair_outcome: str
    requires_certification: bool
    assembled_by_id: Optional[str]
    capacity_window_id: Optional[str]
    quote_attention_required: bool
    invoiced_total_cents: Optional[int]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict, total=False):
    id: str
    repair_order_id: str
    findings_summary: str
    recommended_action: str
    estimated_labor_hours: float
    part_lines: List[Dict[str, Any]]
    report_status: str
    inspector_id: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    repair_order_id: str
    capacity_window_id: str
    revision: int
    status: str
    labor_hours: float
    labor_rate_cents: int
    part_lines: List[Dict[str, Any]]
    pricing_variant: str
    surge_multiplier_applied: float
    parts_subtotal_cents: int
    labor_cents: int
    total_cents: int
    supersedes_quote_id: Optional[str]
    issued_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    part_number: str
    description: str
    unit_price_cents: int
    aftermarket_allowed: bool
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PoolUnit(TypedDict, total=False):
    id: str
    customer_id: str
    asset_id: str
    pool_status: str
    reserved_for_ro_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestRun(TypedDict, total=False):
    id: str
    repair_order_id: str
    run_number: int
    test_type: str
    measured_points: List[Dict[str, Any]]
    max_deviation_pct: float
    weighted_deviation_pct: float
    verdict: str
    tested_by_id: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    repair_order_id: str
    tag_number: str
    set_pressure_psig: float
    seat_leakage_class: str
    certified_by_id: str
    cert_status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityWindow(TypedDict, total=False):
    id: str
    label: str
    window_start: str
    window_end: str
    bay_hours_capacity: int
    bay_hours_reserved: int
    window_posture: str
    created_at: str
    updated_at: str
    version: int
