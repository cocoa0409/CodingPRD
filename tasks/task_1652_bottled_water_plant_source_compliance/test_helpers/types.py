"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    SOURCE_MONITOR = "SourceMonitor"
    QA_OFFICER = "QAOfficer"
    PRODUCTION_LEAD = "ProductionLead"
    SANITATION_LEAD = "SanitationLead"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class Posture(str, Enum):
    GREEN = "GREEN"
    WATCH = "WATCH"
    BREACH = "BREACH"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    SOURCE_TEST_FAIL = "SOURCE_TEST_FAIL"
    TEST_OVERDUE = "TEST_OVERDUE"


class SourceClassification(str, Enum):
    SPRING = "SPRING"
    WELL = "WELL"
    MUNICIPAL = "MUNICIPAL"


class WithdrawalEventStatus(str, Enum):
    RECORDED = "RECORDED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class TreatmentRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    REPROCESSING = "REPROCESSING"
    CANCELLED = "CANCELLED"


class LabTestType(str, Enum):
    SOURCE_RAW = "SOURCE_RAW"
    FINISHED_PRODUCT = "FINISHED_PRODUCT"
    BOTTLE_SANITATION = "BOTTLE_SANITATION"


class LabTestResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class LabTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"


class LabTestOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class PreformDeliveryStatus(str, Enum):
    PENDING_QC = "PENDING_QC"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class QcVerdict(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LabelClassification(str, Enum):
    SPRING = "SPRING"
    PURIFIED = "PURIFIED"


class LotStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    QA_HOLD = "QA_HOLD"
    RELEASED = "RELEASED"
    REWORK = "REWORK"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    RECOVERING = "RECOVERING"
    CLOSED = "CLOSED"


class BottleStatus(str, Enum):
    SANITIZED = "SANITIZED"
    FILLED = "FILLED"
    WITH_CUSTOMER = "WITH_CUSTOMER"
    RETURNED_DIRTY = "RETURNED_DIRTY"
    IN_WASH = "IN_WASH"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class WasherUnit(str, Enum):
    WASHER_A = "WASHER_A"
    WASHER_B = "WASHER_B"


class WashBatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id/created_at/updated_at/version
# (PRD §2.5)
# ---------------------------------------------------------------------------

class Plant(TypedDict, total=False):
    id: str
    name: str
    compliance_posture: str
    ops_run_index: int
    bottle_gross_pool_units: int
    bottle_sanitized_pool_units: int
    created_at: str
    updated_at: str
    version: int


class WaterSourcePermit(TypedDict, total=False):
    id: str
    plant_id: str
    permit_number: str
    source_classification: str
    daily_cap_gallons: int
    monthly_cap_gallons: int
    valid_from: str
    valid_to: str
    status: str
    suspension_reason: Optional[str]
    withdrawn_today_provisional_gallons: int
    withdrawn_today_certified_gallons: int
    withdrawn_month_provisional_gallons: int
    withdrawn_month_certified_gallons: int
    created_at: str
    updated_at: str
    version: int


class WithdrawalEvent(TypedDict, total=False):
    id: str
    permit_id: str
    withdrawal_date: str
    gallons: int
    meter_reading_start_gallons: int
    meter_reading_end_gallons: int
    status: str
    supersedes_event_id: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatmentRun(TypedDict, total=False):
    id: str
    plant_id: str
    source_permit_id: str
    scheduled_start: str
    scheduled_end: str
    uv_dose_mj_cm2: float
    ozone_ct_mg_min_l: float
    turbidity_ntu: float
    micro_pore_micron: float
    ro_rejection_pct: Optional[float]
    status: str
    validation_round: int
    parameters_recorded_by_user_id: Optional[str]
    validated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabTest(TypedDict, total=False):
    id: str
    plant_id: str
    test_type: str
    subject_permit_id: Optional[str]
    subject_lot_id: Optional[str]
    subject_wash_batch_id: Optional[str]
    due_date: str
    result: str
    status: str
    collected_at: Optional[str]
    origin: str
    created_at: str
    updated_at: str
    version: int


class BottlingLine(TypedDict, total=False):
    id: str
    plant_id: str
    line_code: str
    daily_capacity_units: int
    preform_on_hand_units: int
    preform_reserved_units: int
    preform_free_units: int
    preform_reorder_quantity: int
    created_at: str
    updated_at: str
    version: int


class PreformDelivery(TypedDict, total=False):
    id: str
    line_id: str
    supplier: str
    delivered_units: int
    accepted_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLot(TypedDict, total=False):
    id: str
    line_id: str
    treatment_run_id: str
    label_classification: str
    planned_units: int
    produced_units: Optional[int]
    scheduled_start: str
    scheduled_end: str
    status: str
    rework_count: int
    recall_id: Optional[str]
    completed_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallEvent(TypedDict, total=False):
    id: str
    plant_id: str
    reason: str
    status: str
    units_in_scope: int
    units_recovered: int
    created_at: str
    updated_at: str
    version: int


class ReturnableBottle(TypedDict, total=False):
    id: str
    plant_id: str
    bottle_code: str
    wash_cycle_count: int
    status: str
    last_wash_batch_id: Optional[str]
    current_wash_batch_id: Optional[str]
    last_filled_lot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WashBatch(TypedDict, total=False):
    id: str
    plant_id: str
    washer_unit: str
    scheduled_start: str
    scheduled_end: str
    rinse_temp_c: float
    sanitizer_ppm: float
    status: str
    bottle_count: int
    created_at: str
    updated_at: str
    version: int


class PerSourceBreakdownEntry(TypedDict, total=False):
    permit_id: str
    gallons: int
    acre_feet: float


class CommunityWaterReport(TypedDict, total=False):
    id: str
    plant_id: str
    period_year: int
    period_month: int
    status: str
    total_withdrawn_gallons: int
    total_acre_feet: float
    per_source_breakdown: List[PerSourceBreakdownEntry]
    addendum_of_report_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
