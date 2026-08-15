"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"
    SHOP_SCHEDULER = "ShopScheduler"
    FURNACE_OPERATOR = "FurnaceOperator"
    CALIBRATION_TECH = "CalibrationTech"
    QUALITY_ENGINEER = "QualityEngineer"
    NADCAP_AUDITOR = "NadcapAuditor"
    CUSTOMER = "Customer"


class LiabilityTier(str, Enum):
    STANDARD = "STANDARD"
    EXTENDED = "EXTENDED"


class QuenchMedia(str, Enum):
    OIL = "OIL"
    WATER = "WATER"
    POLYMER = "POLYMER"
    AIR = "AIR"
    GAS = "GAS"


class FurnaceClass(str, Enum):
    CLASS_1 = "CLASS_1"
    CLASS_2 = "CLASS_2"
    CLASS_3 = "CLASS_3"
    CLASS_5 = "CLASS_5"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class QualificationStatus(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    SURVEY_OVERDUE = "SURVEY_OVERDUE"
    CALIBRATION_OVERDUE = "CALIBRATION_OVERDUE"
    QUALIFIED = "QUALIFIED"


class PyrometryRecordType(str, Enum):
    TUS = "TUS"
    INSTRUMENT_CALIBRATION = "INSTRUMENT_CALIBRATION"


class PyrometryResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ServiceLane(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class ProcessingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCHEDULED = "SCHEDULED"
    IN_PROCESS = "IN_PROCESS"
    PROCESSED = "PROCESSED"
    AWAITING_RETREAT = "AWAITING_RETREAT"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"
    CANCELLED = "CANCELLED"


class QualityStatus(str, Enum):
    PENDING_TEST = "PENDING_TEST"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class LoadBatchStatus(str, Enum):
    BUILDING = "BUILDING"
    HOLD = "HOLD"
    RELEASED = "RELEASED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DispositionStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"


class DispositionDecision(str, Enum):
    RE_TREAT = "RE_TREAT"
    SCRAP = "SCRAP"
    RETURN_AS_IS = "RETURN_AS_IS"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class AuditPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"


# --- Entity payloads (PRD §2.4 common quartet: id, created_at, updated_at,
# version; append-only evidence records carry id and created_at only) ---


class CustomerAccount(TypedDict, total=False):
    id: str
    name: str
    liability_tier: str
    credit_hold: bool
    outstanding_liability_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class FurnaceRecipe(TypedDict, total=False):
    id: str
    alloy_code: str
    spec_code: str
    soak_temp_f: int
    soak_tolerance_f: int
    min_soak_minutes: int
    quench_media: str
    required_furnace_class: str
    max_retreats: int
    fixture_distortion_allowance_in: float
    hardness_min_hrc: int
    hardness_max_hrc: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Furnace(TypedDict, total=False):
    id: str
    furnace_code: str
    furnace_class: str
    max_load_weight_lb: int
    quench_media_supported: List[str]
    qualification_status: str
    current_tus_due_at: Optional[str]
    current_calibration_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PyrometryRecord(TypedDict, total=False):
    # Append-only evidence record: id + created_at only, no updated_at/version.
    id: str
    furnace_id: str
    record_type: str
    performed_at: str
    result: str
    instrument_id: Optional[str]
    next_due_at: str
    created_at: str


class WorkOrder(TypedDict, total=False):
    id: str
    customer_id: str
    recipe_id: str
    part_quantity: int
    received_weight_lb: float
    declared_value_cents: int
    processing_charge_cents: int
    service_lane: str
    guaranteed_turnaround_hours: Optional[int]
    received_at: str
    promised_due_at: Optional[str]
    shipped_at: Optional[str]
    turnaround_breached: bool
    rush_surcharge_quoted_cents: int
    rush_surcharge_final_cents: Optional[int]
    energy_surcharge_cents: Optional[int]
    retreat_count: int
    processing_status: str
    quality_status: str
    created_at: str
    updated_at: str
    version: int


class LoadBatch(TypedDict, total=False):
    id: str
    furnace_id: str
    recipe_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    total_weight_lb: float
    out_of_spec: bool
    total_energy_surcharge_cents: Optional[int]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoadAssignment(TypedDict, total=False):
    id: str
    load_batch_id: str
    work_order_id: str
    status: str
    assigned_at: str
    created_at: str
    updated_at: str
    version: int


class LoadThermocoupleReading(TypedDict, total=False):
    # Append-only evidence record: id + created_at only.
    id: str
    load_batch_id: str
    channel: str
    recorded_at: str
    temp_f: int
    created_at: str


class InspectionTest(TypedDict, total=False):
    # Append-only evidence record: id + created_at only.
    id: str
    work_order_id: str
    recorded_by_user_id: str
    hardness_readings: List[float]
    measured_distortion_in: float
    avg_hardness_hrc: float
    result: str
    created_at: str


class DispositionCase(TypedDict, total=False):
    id: str
    work_order_id: str
    inspection_test_id: str
    status: str
    decision: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiabilityClaim(TypedDict, total=False):
    id: str
    work_order_id: str
    customer_id: str
    payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditPackage(TypedDict, total=False):
    id: str
    furnace_id: str
    load_batch_ids: List[str]
    evidence_manifest: dict
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
