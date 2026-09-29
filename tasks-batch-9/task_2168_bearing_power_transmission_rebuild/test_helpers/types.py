"""Domain types for the Bearing & Power-Transmission Rebuild API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    PLANNER = "Planner"
    INSPECTOR = "Inspector"
    RELIABILITY_ENGINEER = "ReliabilityEngineer"
    CUSTOMER = "Customer"


class Criticality(str, Enum):
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"


class DutyClass(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    INTERMITTENT = "INTERMITTENT"
    STANDBY = "STANDBY"


class ConditionGrade(str, Enum):
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    GRADE_C = "GRADE_C"
    GRADE_D = "GRADE_D"
    SCRAP = "SCRAP"


class CoreUnitStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INSPECTING = "INSPECTING"
    GRADED = "GRADED"
    REBUILDING = "REBUILDING"
    REBUILT = "REBUILT"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"
    RETURNED_AS_IS = "RETURNED_AS_IS"


class WorkStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PartLineStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SourceClass(str, Enum):
    OEM = "OEM"
    AFTERMARKET = "AFTERMARKET"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class BandResult(str, Enum):
    IN_SPEC = "IN_SPEC"
    REWORKABLE = "REWORKABLE"
    OUT_OF_SPEC = "OUT_OF_SPEC"


class LifeScoreVariant(str, Enum):
    COMPOSITE = "COMPOSITE"
    CONSERVATIVE = "CONSERVATIVE"


class FailureCauseCode(str, Enum):
    OUTER_RACE_SPALL = "OUTER_RACE_SPALL"
    INNER_RACE_SPALL = "INNER_RACE_SPALL"
    MISALIGNMENT = "MISALIGNMENT"
    LOOSE_FIT = "LOOSE_FIT"
    LUBRICATION_FAILURE = "LUBRICATION_FAILURE"
    NORMAL_WEAR = "NORMAL_WEAR"
    WORKMANSHIP = "WORKMANSHIP"
    UNDETERMINED = "UNDETERMINED"


class CauseConfidence(str, Enum):
    ASSERTED = "ASSERTED"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IsoZone(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ReservationStatus(str, Enum):
    QUEUED = "QUEUED"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class InstallationStatus(str, Enum):
    INSTALLED = "INSTALLED"
    RUNNING = "RUNNING"
    REMOVED_PLANNED = "REMOVED_PLANNED"
    FAILED_IN_SERVICE = "FAILED_IN_SERVICE"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CREDITED = "CREDITED"


class GoverningBasis(str, Enum):
    HOURS = "HOURS"
    CALENDAR = "CALENDAR"
    GOODWILL = "GOODWILL"


class CreditNoteKind(str, Enum):
    CORE_EXCHANGE = "CORE_EXCHANGE"
    WARRANTY_PRORATA = "WARRANTY_PRORATA"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class CreditNoteStatus(str, Enum):
    POSTED = "POSTED"
    VOID = "VOID"


# --------------------------------------------------------------------------
# Entity shapes. Records that carry updated_at + version are marked as such;
# Measurement and VibrationReading are immutable observations and carry only
# id and created_at.
# --------------------------------------------------------------------------

class Customer(TypedDict):
    id: str
    name: str
    account_code: str
    contact_email: Optional[str]
    core_credit_balance_cents: int
    warranty_credit_balance_cents: int
    manual_credit_balance_cents: int
    total_credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class CustomerAsset(TypedDict):
    id: str
    customer_id: str
    asset_tag: str
    criticality: str
    duty_class: str
    site_code: str
    created_at: str
    updated_at: str
    version: int


class ClearanceStandard(TypedDict):
    id: str
    model_code: str
    base_core_value_cents: int
    max_rebuild_count: int
    warranty_hours: int
    warranty_months: int
    cleanroom_required: bool
    required_feature_codes: List[str]
    feature_bands: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Bench(TypedDict):
    id: str
    bench_code: str
    parallel_slots: int
    cleanroom: bool
    committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class CoreUnit(TypedDict):
    id: str
    customer_id: str
    clearance_standard_id: str
    serial_no: str
    model_code: str
    rebuild_count: int
    declared_condition_grade: str
    condition_grade: Optional[str]
    status: str
    provisional_core_credit_cents: int
    final_core_credit_cents: Optional[int]
    replacement_core_unit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RebuildOrder(TypedDict):
    id: str
    customer_id: str
    core_unit_id: str
    customer_asset_id: str
    labor_hours: float
    work_status: str
    approval_status: str
    expedited: bool
    expedite_reason: Optional[str]
    emergency_ref: Optional[str]
    part_revision_counter: int
    quoted_part_revision: Optional[int]
    parts_subtotal_cents: Optional[int]
    labor_cents: Optional[int]
    pre_credit_subtotal_cents: Optional[int]
    expedite_surcharge_cents: Optional[int]
    gross_total_cents: Optional[int]
    core_credit_applied_cents: Optional[int]
    quote_total_cents: Optional[int]
    covered_base_cents: Optional[int]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    rebuild_order_id: str
    linked_vibration_reading_id: Optional[str]
    status: str
    inspector_note: Optional[str]
    cause_code_override: Optional[str]
    submitted_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    revision_count: int
    life_score_variant: Optional[str]
    remaining_life_score: Optional[int]
    remaining_life_grade: Optional[str]
    failure_cause_code: Optional[str]
    cause_confidence: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Measurement(TypedDict):
    """Immutable observation: id and created_at only, no updated_at/version."""
    id: str
    inspection_id: str
    feature_code: str
    measured_um: int
    sequence_no: int
    band_result: str
    deviation_ratio: float
    feature_score: float
    created_at: str


class PartLine(TypedDict):
    id: str
    rebuild_order_id: str
    part_no: str
    source_class: str
    qty: int
    unit_cost_cents: int
    engineering_waiver_ref: Optional[str]
    approval_status: str
    revision_count: int
    decision_note: Optional[str]
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class VibrationReading(TypedDict):
    """Immutable observation: id and created_at only, no updated_at/version."""
    id: str
    customer_asset_id: str
    reading_at: str
    overall_velocity_mm_s: float
    bpfo_amplitude_g: float
    bpfi_amplitude_g: float
    baseline_amplitude_g: float
    iso_zone: str
    defect_ratio_outer: float
    defect_ratio_inner: float
    created_at: str


class BenchReservation(TypedDict):
    id: str
    rebuild_order_id: str
    bench_id: str
    window_start_at: str
    window_end_at: str
    queue_if_full: bool
    status: str
    window_minutes: int
    promoted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Installation(TypedDict):
    id: str
    core_unit_id: str
    customer_asset_id: str
    rebuild_order_id: str
    in_service_start_at: str
    run_hours: float
    status: str
    removed_at: Optional[str]
    failed_at: Optional[str]
    warranty_hours_snapshot: int
    warranty_months_snapshot: int
    covered_base_cents_snapshot: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    installation_id: str
    claimed_reason: str
    status: str
    submitted_at: str
    elapsed_days: int
    hours_consumed_fraction: float
    calendar_consumed_fraction: float
    governing_basis: str
    remaining_fraction: float
    pro_rata_credit_cents: int
    adjudication_note: Optional[str]
    adjudicated_by_user_id: Optional[str]
    info_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditNote(TypedDict):
    id: str
    customer_id: str
    kind: str
    amount_cents: int
    status: str
    core_unit_id: Optional[str]
    warranty_claim_id: Optional[str]
    memo: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
