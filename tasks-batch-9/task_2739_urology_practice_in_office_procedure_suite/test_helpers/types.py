"""
Entity shapes and enumerations of the Urology Practice & In-Office Procedure
Suite API.

Every entity of this contract carries the same four common fields — a
server-minted ``id``, ``created_at`` and ``updated_at`` timestamps and an
integer ``version`` that starts at 1 and rises by one on every mutation — so
each TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role vocabulary ────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    SCHEDULER = "Scheduler"
    UROLOGIST = "Urologist"
    PROCEDURE_NURSE = "ProcedureNurse"
    STERILE_PROCESSING_TECH = "SterileProcessingTech"
    PATHOLOGY_LIAISON = "PathologyLiaison"
    PELVIC_HEALTH_COORDINATOR = "PelvicHealthCoordinator"


class RoleType(str, Enum):
    UROLOGIST = "UROLOGIST"
    RN = "RN"
    TECH = "TECH"
    SCHEDULER = "SCHEDULER"
    PATHOLOGY_LIAISON = "PATHOLOGY_LIAISON"
    PELVIC_COORDINATOR = "PELVIC_COORDINATOR"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AntibioticAllergyClass(str, Enum):
    NONE = "NONE"
    FLUOROQUINOLONE = "FLUOROQUINOLONE"
    CEPHALOSPORIN = "CEPHALOSPORIN"
    SULFA = "SULFA"
    AMINOGLYCOSIDE = "AMINOGLYCOSIDE"


class RoomType(str, Enum):
    CYSTO_SUITE = "CYSTO_SUITE"
    URODYNAMICS_LAB = "URODYNAMICS_LAB"
    IMAGING_BAY = "IMAGING_BAY"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CleanupClass(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_ROOM = "IN_ROOM"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ClearanceStatus(str, Enum):
    PENDING_PREP = "PENDING_PREP"
    PREP_ACKNOWLEDGED = "PREP_ACKNOWLEDGED"
    PREP_WAIVED = "PREP_WAIVED"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class DeviceState(str, Enum):
    NONE = "NONE"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    WASTED = "WASTED"


class AntibioticAgent(str, Enum):
    CIPROFLOXACIN = "CIPROFLOXACIN"
    CEFAZOLIN = "CEFAZOLIN"
    TMP_SMX = "TMP_SMX"
    GENTAMICIN = "GENTAMICIN"


class AntibioticRoute(str, Enum):
    ORAL = "ORAL"
    IV = "IV"


class AntibioticStatus(str, Enum):
    ORDERED = "ORDERED"
    ADMINISTERED = "ADMINISTERED"
    CANCELLED = "CANCELLED"


class ScopeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    SOILED = "SOILED"
    REPROCESSING = "REPROCESSING"
    QUARANTINED = "QUARANTINED"


class ReprocessingStage(str, Enum):
    PRECLEAN = "PRECLEAN"
    LEAK_TEST = "LEAK_TEST"
    MANUAL_CLEAN = "MANUAL_CLEAN"
    HIGH_LEVEL_DISINFECT = "HIGH_LEVEL_DISINFECT"
    DRY_STORE = "DRY_STORE"


class StageOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class LogStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SpecimenType(str, Enum):
    PROSTATE_CORE = "PROSTATE_CORE"
    BLADDER_WASHING = "BLADDER_WASHING"
    BIOPSY_FRAGMENT = "BIOPSY_FRAGMENT"


class ConditionOnReceipt(str, Enum):
    INTACT = "INTACT"
    COMPROMISED = "COMPROMISED"


class ChainStatus(str, Enum):
    COLLECTED = "COLLECTED"
    ACCESSIONED = "ACCESSIONED"
    RESULTED = "RESULTED"
    REJECTED = "REJECTED"


class PathologyResult(str, Enum):
    BENIGN = "BENIGN"
    ATYPICAL = "ATYPICAL"
    MALIGNANT = "MALIGNANT"
    INSUFFICIENT = "INSUFFICIENT"


class NotificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    ATTEMPTED = "ATTEMPTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class RecallProtocol(str, Enum):
    STONE = "STONE"
    BLADDER_CANCER = "BLADDER_CANCER"
    PROSTATE = "PROSTATE"


class RiskTier(str, Enum):
    LOW = "LOW"
    INTERMEDIATE = "INTERMEDIATE"
    HIGH = "HIGH"


class DueBasis(str, Enum):
    PROTOCOL_ANCHORED = "PROTOCOL_ANCHORED"
    EVENT_ANCHORED = "EVENT_ANCHORED"


class RecallStatus(str, Enum):
    SCHEDULED_DUE = "SCHEDULED_DUE"
    OVERDUE = "OVERDUE"
    SATISFIED = "SATISFIED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class TherapyProgram(str, Enum):
    PELVIC_FLOOR_PT = "PELVIC_FLOOR_PT"
    BEHAVIORAL_TRAINING = "BEHAVIORAL_TRAINING"
    BIOFEEDBACK = "BIOFEEDBACK"


class ReferralStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WAITLISTED = "WAITLISTED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class DeviceClass(str, Enum):
    SINGLE_USE_SCOPE_SHEATH = "SINGLE_USE_SCOPE_SHEATH"
    BIOPSY_NEEDLE = "BIOPSY_NEEDLE"
    URODYNAMICS_CATHETER_KIT = "URODYNAMICS_CATHETER_KIT"
    ULTRASOUND_PROBE_COVER = "ULTRASOUND_PROBE_COVER"


class BillingBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class BillingStatus(str, Enum):
    CONSIGNED = "CONSIGNED"
    PARTIALLY_INVOICED = "PARTIALLY_INVOICED"
    INVOICED = "INVOICED"
    RETURNED = "RETURNED"


# ─── Entities ───────────────────────────────────────────────────────────────
class Provider(TypedDict):
    id: str
    full_name: str
    npi: str
    role_type: str
    credential_status: str
    hld_certified: bool
    ultrasound_accreditation_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    primary_urologist_id: str
    egfr: float
    anticoagulant_flag: bool
    antibiotic_allergy_class: str
    outstanding_recall_count: int
    open_notification_count: int
    created_at: str
    updated_at: str
    version: int


class ProcedureRoom(TypedDict):
    id: str
    name: str
    room_type: str
    turnover_minutes: int
    room_status: str
    accreditation_body: Optional[str]
    accreditation_expires_on: Optional[str]
    occupied_block_count: int
    created_at: str
    updated_at: str
    version: int


class ProcedureType(TypedDict):
    id: str
    code: str
    base_minutes: int
    cleanup_class: str
    allowed_room_type: str
    requires_scope: bool
    requires_specimen: bool
    requires_antibiotic: bool
    consignment_required: bool
    single_use_device_sku: Optional[str]
    required_prep_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class ProcedureCase(TypedDict):
    id: str
    patient_id: str
    procedure_type_id: str
    room_id: str
    primary_provider_id: str
    scheduled_start_at: str
    procedure_minutes: int
    turnover_minutes: int
    scheduled_end_at: str
    block_end_at: str
    schedule_status: str
    clearance_status: str
    acknowledged_prep_codes: List[str]
    clearance_block_reason: Optional[str]
    scope_asset_id: Optional[str]
    device_lot_id: Optional[str]
    device_quantity: int
    device_state: str
    checked_in_at: Optional[str]
    completed_at: Optional[str]
    cancel_reason_code: Optional[str]
    blocking_reason_codes: List[str]
    indication_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AntibioticOrder(TypedDict):
    id: str
    case_id: str
    ordered_by_provider_id: str
    requested_agent: str
    agent: str
    dose_mg: int
    route: str
    prophylaxis_window_start_at: str
    administered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScopeAsset(TypedDict):
    id: str
    serial_number: str
    scope_model: str
    channel_count: int
    status: str
    cycles_since_leak_test: int
    leak_test_required: bool
    hld_pass_at: Optional[str]
    reprocess_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReprocessingLog(TypedDict):
    id: str
    scope_asset_id: str
    case_id: Optional[str]
    stage: str
    performed_by_provider_id: str
    attested_by_provider_id: Optional[str]
    started_at: str
    completed_at: Optional[str]
    outcome: Optional[str]
    log_status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    case_id: str
    collected_by_provider_id: str
    container_label: str
    specimen_type: str
    site_code: str
    collected_at: str
    accession_number: Optional[str]
    received_at: Optional[str]
    condition_on_receipt: Optional[str]
    chain_status: str
    pathology_result: Optional[str]
    result_at: Optional[str]
    notification_status: str
    notification_attempt_count: int
    escalation_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveillanceRecall(TypedDict):
    id: str
    patient_id: str
    protocol: str
    risk_tier: str
    anchor_date: str
    interval_months: int
    due_on: str
    due_basis: str
    status: str
    lapse_days: int
    predecessor_recall_id: Optional[str]
    source_specimen_id: Optional[str]
    satisfying_case_id: Optional[str]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PelvicHealthReferral(TypedDict):
    id: str
    patient_id: str
    source_case_id: Optional[str]
    program: str
    requested_visits: int
    visits_authorized: int
    visits_used: int
    visits_remaining: int
    visits_forfeited: int
    status: str
    waitlist_position: Optional[int]
    therapy_start_by: Optional[str]
    first_visit_date: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsignmentLot(TypedDict):
    id: str
    supplier_name: str
    sku: str
    device_class: str
    quantity_received: int
    quantity_available: int
    quantity_reserved: int
    quantity_consumed: int
    quantity_returned: int
    quantity_wasted: int
    unit_price_cents: int
    lot_expires_on: str
    billed_amount_cents: int
    billing_basis: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class CaseReadiness(TypedDict):
    case_id: str
    schedule_status: str
    clearance_status: str
    blocking_reason_codes: List[str]
    first_blocking_reason_code: Optional[str]
    check_in_allowed: bool


class RecallSweep(TypedDict):
    swept_at: str
    recomputed_recall_count: int
    overdue_recall_count: int
    restored_recall_count: int
    escalated_specimen_count: int
