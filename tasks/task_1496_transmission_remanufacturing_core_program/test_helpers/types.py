"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INVENTORY_PLANNER = "InventoryPlanner"
    REMAN_PLANNER = "RemanPlanner"
    REMAN_TECHNICIAN = "RemanTechnician"
    CALIBRATOR = "Calibrator"
    DYNO_OPERATOR = "DynoOperator"
    CORE_INTAKE_CLERK = "CoreIntakeClerk"
    CORE_INSPECTOR = "CoreInspector"
    INSTALLER = "Installer"
    WARRANTY_ADJUSTER = "WarrantyAdjuster"
    ANY = "Any"


class RemanOrderStatus(str, Enum):
    QUEUED = "QUEUED"
    PART_HOLD = "PART_HOLD"
    ASSEMBLY = "ASSEMBLY"
    CALIBRATION = "CALIBRATION"
    DYNO_QUEUE = "DYNO_QUEUE"
    REWORK = "REWORK"
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    DYNO_PASSED = "DYNO_PASSED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class CalStatus(str, Enum):
    NONE = "NONE"
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"


class CoreSettlementStatus(str, Enum):
    PENDING = "PENDING"
    CLOSED = "CLOSED"


class InterchangeTier(str, Enum):
    DIRECT = "DIRECT"
    ADAPTED = "ADAPTED"


class DynoBookingStatus(str, Enum):
    BOOKED = "BOOKED"


class DynoVerdict(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class CoreGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECTED = "REJECTED"


class CoreUnitStatus(str, Enum):
    RECEIVED = "RECEIVED"
    GRADED = "GRADED"
    REJECTED = "REJECTED"
    RE_INSPECTION = "RE_INSPECTION"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_GRADE = "AWAITING_GRADE"
    SETTLED_FULL = "SETTLED_FULL"
    SETTLED_PARTIAL = "SETTLED_PARTIAL"
    FORFEITED = "FORFEITED"
    DISPUTED = "DISPUTED"
    SETTLED_ADJUSTED = "SETTLED_ADJUSTED"


class FailureCode(str, Enum):
    CONVERTER_FAILURE = "CONVERTER_FAILURE"
    GEAR_CLUNK = "GEAR_CLUNK"
    PRESSURE_LEAK = "PRESSURE_LEAK"
    ELECTRICAL_TCM = "ELECTRICAL_TCM"


class AllowancePolicy(str, Enum):
    BOOK_HOURS = "BOOK_HOURS"
    ACTUAL_HOURS = "ACTUAL_HOURS"


class RoutingType(str, Enum):
    RETURN_TO_PLANT = "RETURN_TO_PLANT"
    RETURN_TO_DISTRIBUTOR = "RETURN_TO_DISTRIBUTOR"
    LOCAL_SCRAP = "LOCAL_SCRAP"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class ReturnStatus(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    IN_TRANSIT = "IN_TRANSIT"
    DISPOSITIONED = "DISPOSITIONED"


class CoreFinding(str, Enum):
    TORQUE_CONVERTER_MISSING = "TORQUE_CONVERTER_MISSING"
    VALVE_BODY_MISSING = "VALVE_BODY_MISSING"
    SENSOR_HARNESS_MISSING = "SENSOR_HARNESS_MISSING"
    BELL_HOUSING_DAMAGED = "BELL_HOUSING_DAMAGED"
    PAN_MISSING = "PAN_MISSING"


# --- Entity bodies (total=False: nullable system fields may be null) ---------

class TransmissionModel(TypedDict, total=False):
    id: str
    model_code: str
    year_start: int
    year_end: int
    make: str
    model: str
    core_deposit_cents: int
    flat_rate_hours: float
    labor_cap_cents: int
    warranty_days: int
    dyno_targets: List[Dict[str, Any]]
    required_parts: List[Dict[str, Any]]
    spec_version: int
    created_at: str
    updated_at: str
    version: int


class HardPart(TypedDict, total=False):
    id: str
    part_number: str
    part_family: str
    unit_cost_cents: int
    qty_on_hand: int
    qty_reserved: int
    availability: int
    created_at: str
    updated_at: str
    version: int


# Immutable record (PRD §2.4): carries only id + created_at, no updated_at/version.
class InterchangeMapping(TypedDict, total=False):
    id: str
    hard_part_id: str
    transmission_model_id: str
    tier: str
    created_at: str


class RemanOrder(TypedDict, total=False):
    id: str
    transmission_model_id: str
    buyer_ref: str
    pinned_spec: Dict[str, Any]
    model_spec_version_pin: int
    status: str
    shortage_parts: List[str]
    reserved_parts: List[Dict[str, Any]]
    surcharge_labor_minutes: int
    cal_status: str
    cal_generation: int
    solenoid_trims: Optional[List[float]]
    tcm_flash_version: Optional[str]
    tcm_flash_version_applied: Optional[str]
    cal_created_by_id: Optional[str]
    cal_created_at: Optional[str]
    dyno_attempts_used: int
    last_shift_quality_score: Optional[float]
    core_settlement_status: str
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable record (PRD §2.4).
class DynoBooking(TypedDict, total=False):
    id: str
    reman_order_id: str
    dyno_cell_code: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str


# Immutable record (PRD §2.4).
class DynoTestRun(TypedDict, total=False):
    id: str
    reman_order_id: str
    dyno_booking_id: str
    attempt_number: int
    gear_pressures_kpa: List[float]
    shift_quality_score: float
    verdict: str
    created_at: str


class CoreUnit(TypedDict, total=False):
    id: str
    core_deposit_invoice_id: str
    dock_code: str
    dock_start_utc: str
    dock_end_utc: str
    received_at: str
    days_late: int
    case_cracked: Optional[bool]
    findings: Optional[List[str]]
    deduction_score: Optional[int]
    grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoreDepositInvoice(TypedDict, total=False):
    id: str
    reman_order_id: str
    buyer_ref: str
    deposit_cents: int
    issued_at: str
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    forfeited_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    reman_order_id: str
    installer_id: str
    failure_code: str
    claimed_labor_hours: float
    installer_labor_rate_cents: int
    allowance_policy: str
    labor_allowance_cents: Optional[int]
    routing_type: Optional[str]
    return_required: Optional[bool]
    claim_status: str
    return_status: str
    deny_reason: Optional[str]
    salvaged_parts: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int
